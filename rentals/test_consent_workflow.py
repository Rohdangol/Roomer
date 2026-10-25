"""Focused checks for consent isolation, permissions, reservations and date transitions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from listings.models import RoomListing
from notifications.models import Notification
from .models import AgreementReview, RentalAgreement, RentalRequest
from .tests import RentalFixtures
from .services import decide_request
from .agreement_services import (activate_scheduled, confirm_agreement, local_today,
    prepare_agreement, request_agreement_changes, review_agreement, send_agreement)


class ConsentFixture(RentalFixtures):
    def accepted(self):
        application = self.submit()
        decide_request(self.owner, application.pk, "accept")
        return RentalAgreement.objects.get(rental_request=application)

    def prepared(self, agreement, start=None):
        start = start or local_today()
        return prepare_agreement(self.owner, agreement.rental_request_id, {
            "monthly_rent": 10000, "security_deposit": 0, "payment_due_day": 5,
            "start_date": start, "end_date": start + timedelta(days=3),
            "additional_terms": "Agreed test rental terms."}, agreement.current_terms_id)

    def reviewer(self):
        return User.objects.create_superuser(username="consent-admin", email="consent-admin@example.test")


class ConsentWorkflowTests(ConsentFixture, TestCase):
    def test_acceptance_reserves_and_creates_only_one_draft(self):
        first = self.submit()
        other = self.submit(self.other)
        decide_request(self.owner, first.pk, "accept")
        decide_request(self.owner, first.pk, "accept")
        agreement = RentalAgreement.objects.get()
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_status, "reserved")
        self.assertEqual(agreement.status, "draft")
        self.assertEqual(agreement.versions.count(), 1)
        self.assertIsNone(agreement.current_terms.end_date)
        with self.assertRaises(ValidationError):
            decide_request(self.owner, other.pk, "accept")
        self.assertEqual(RentalRequest.objects.filter(status="accepted").count(), 1)
        with self.assertRaises(ValidationError):
            send_agreement(self.owner, agreement.pk, agreement.current_terms_id)

    def test_reservation_guard_does_not_depend_on_listing_status_alone(self):
        from listings.services import change_listing_availability
        self.accepted()
        RoomListing.objects.filter(pk=self.listing.pk).update(listing_status="available")
        with self.assertRaises(ValidationError):
            self.submit(self.other)
        with self.assertRaises(ValidationError):
            change_listing_availability(self.owner, self.listing.pk, "archive")

    def test_versions_require_fresh_consent_and_review_history(self):
        agreement = self.prepared(self.accepted())
        admin = self.reviewer()
        old = agreement.current_terms
        send_agreement(self.owner, agreement.pk, old.pk)
        old.refresh_from_db()
        self.assertIsNotNone(old.owner_accepted_at)
        self.assertIsNone(old.tenant_accepted_at)
        with self.assertRaises(ValidationError):
            review_agreement(admin, agreement.pk, old.pk, "approve")
        with self.assertRaises(ValidationError):
            self.prepared(agreement)
        request_agreement_changes(self.tenant, agreement.pk, old.pk, "Please revise the terms.")
        agreement = self.prepared(agreement)
        new = agreement.current_terms
        self.assertIsNone(new.owner_accepted_at)
        self.assertIsNone(new.tenant_accepted_at)
        self.assertIsNone(new.approved_at)
        send_agreement(self.owner, agreement.pk, new.pk)
        with self.assertRaises(ValidationError):
            confirm_agreement(self.tenant, agreement.pk, old.pk)
        confirm_agreement(self.tenant, agreement.pk, new.pk)
        with self.assertRaises(ValidationError):
            review_agreement(admin, agreement.pk, new.pk, "return", "  ")
        review_agreement(admin, agreement.pk, new.pk, "return", "Clarify the terms.")
        agreement = self.prepared(agreement)
        current = agreement.current_terms
        send_agreement(self.owner, agreement.pk, current.pk)
        confirm_agreement(self.tenant, agreement.pk, current.pk)
        review_agreement(admin, agreement.pk, current.pk, "approve")
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "active")
        self.assertEqual(AgreementReview.objects.count(), 3)
        old.refresh_from_db()
        self.assertIsNotNone(old.owner_accepted_at)
        self.assertIsNone(old.tenant_accepted_at)

    def test_permissions_csrf_consent_and_real_role_screens(self):
        agreement = self.prepared(self.accepted())
        self.client.force_login(self.owner)
        send_url = reverse("accounts:owner_agreement_send", args=[agreement.pk])
        self.client.post(send_url, {"terms_id": agreement.current_terms_id})
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "draft")
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(send_url, {"terms_id": agreement.current_terms_id, "confirm": "on"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:owner_agreement_details", args=[agreement.pk])).status_code, 200)
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("accounts:agreement_details", args=[agreement.pk])).status_code, 404)
        with self.assertRaises(RentalAgreement.DoesNotExist):
            confirm_agreement(self.other, agreement.pk, agreement.current_terms_id)
        staff = User.objects.create_user(username="limited-staff", email="staff@example.test", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_rentalagreement"))
        with self.assertRaises(PermissionDenied):
            review_agreement(staff, agreement.pk, agreement.current_terms_id, "approve")
        self.client.force_login(self.tenant)
        self.assertEqual(self.client.get(reverse("accounts:agreement_details", args=[agreement.pk])).status_code, 200)
        confirm_agreement(self.tenant, agreement.pk, agreement.current_terms_id)
        admin = self.reviewer()
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("accounts:admin_agreement_details", args=[agreement.pk])), "Approve Agreement")
        self.assertEqual(self.client.get(reverse("accounts:admin_agreements")).status_code, 200)

    def test_inclusive_dates_scheduler_idempotency_and_inactive_release(self):
        today = local_today()
        start = today + timedelta(days=2)
        agreement = self.prepared(self.accepted(), start)
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        confirm_agreement(self.tenant, agreement.pk, agreement.current_terms_id)
        review_agreement(self.reviewer(), agreement.pk, agreement.current_terms_id, "approve")
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "scheduled")
        with patch("rentals.agreement_services.local_today", return_value=start):
            self.assertEqual(activate_scheduled(agreement.pk), "activated")
            count = Notification.objects.count()
            self.assertFalse(activate_scheduled(agreement.pk))
            self.assertEqual(Notification.objects.count(), count)
        with patch("rentals.agreement_services.local_today", return_value=agreement.current_terms.end_date):
            self.assertFalse(activate_scheduled(agreement.pk))
        RoomListing.objects.filter(pk=self.listing.pk).update(listing_status="inactive")
        with patch("rentals.agreement_services.local_today", return_value=start + timedelta(days=4)):
            self.assertEqual(activate_scheduled(agreement.pk), "completed")
            count = Notification.objects.count()
            self.assertFalse(activate_scheduled(agreement.pk))
            self.assertEqual(Notification.objects.count(), count)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_status, "inactive")

    def test_late_admin_approval_requires_revised_dates(self):
        agreement = self.prepared(self.accepted())
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        confirm_agreement(self.tenant, agreement.pk, agreement.current_terms_id)
        with patch("rentals.agreement_services.local_today", return_value=local_today() + timedelta(days=1)):
            with self.assertRaises(ValidationError):
                review_agreement(self.reviewer(), agreement.pk, agreement.current_terms_id, "approve")
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "pending_admin")
        self.assertIsNone(agreement.current_terms.approved_at)

    def test_missed_rental_period_completes_without_fake_activation(self):
        start = local_today() + timedelta(days=2)
        agreement = self.prepared(self.accepted(), start)
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        confirm_agreement(self.tenant, agreement.pk, agreement.current_terms_id)
        review_agreement(self.reviewer(), agreement.pk, agreement.current_terms_id, "approve")
        with patch("rentals.agreement_services.local_today", return_value=start + timedelta(days=4)):
            self.assertEqual(activate_scheduled(agreement.pk), "completed")
        agreement.refresh_from_db()
        self.assertIsNone(agreement.activated_at)
        self.assertEqual(agreement.status, "completed")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_status, "available")

    def test_legacy_never_receives_implied_approval_or_automatic_transition(self):
        agreement = self.prepared(self.accepted())
        RentalAgreement.objects.filter(pk=agreement.pk).update(workflow_version=1, status="pending")
        with self.assertRaises(ValidationError):
            send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        self.assertFalse(activate_scheduled(agreement.pk))
        agreement.refresh_from_db()
        self.assertEqual(agreement.workflow_version, 1)
        self.assertIsNone(agreement.current_terms.approved_at)


class ReservationConcurrencyTests(ConsentFixture, TransactionTestCase):
    def setUp(self):
        type(self).setUpTestData()

    def concurrent(self, tasks):
        barrier = Barrier(2)
        def run(task):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                task()
                return True
            except ValidationError:
                return False
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, tasks))

    def test_simultaneous_acceptance_has_one_reservation(self):
        first, second = self.submit(), self.submit(self.other)
        results = self.concurrent([lambda: decide_request(self.owner, first.pk, "accept"), lambda: decide_request(self.owner, second.pk, "accept")])
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(RentalAgreement.objects.count(), 1)
        self.assertEqual(RentalRequest.objects.filter(status="accepted").count(), 1)

    def test_simultaneous_approval_records_one_decision(self):
        agreement = self.prepared(self.accepted(), local_today() + timedelta(days=2))
        admin = self.reviewer()
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        confirm_agreement(self.tenant, agreement.pk, agreement.current_terms_id)
        task = lambda: review_agreement(admin, agreement.pk, agreement.current_terms_id, "approve")
        self.assertEqual(sorted(self.concurrent([task, task])), [False, True])
        self.assertEqual(AgreementReview.objects.filter(decision="admin_approve").count(), 1)


class LegacyMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_existing_binding_terms_without_proof(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        target = ("rentals", "0002_agreementreview_alter_rentalagreement_options_and_more")
        executor.migrate([("rentals", "0001_initial")])
        try:
            # Other apps stay at their current schema while only rentals is rolled back.
            targets = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "rentals"]
            apps = executor.loader.project_state(targets + [("rentals", "0001_initial")]).apps
            UserModel = apps.get_model("accounts", "User")
            owner = UserModel.objects.create(username="legacy-owner", email="legacy-owner@example.test", role="owner")
            tenant = UserModel.objects.create(username="legacy-tenant", email="legacy-tenant@example.test", role="tenant")
            listing = apps.get_model("listings", "RoomListing").objects.create(owner=owner, listing_status="occupied")
            now = timezone.now()
            today = local_today()
            revision = apps.get_model("listings", "ListingRevision").objects.create(listing=listing, version=1,
                title="Historical room", description="Original", city="City", address="Address", latitude=27, longitude=85,
                room_type="single_room", furnishing="furnished", monthly_rent=10000, security_deposit=0,
                available_from=today, maximum_occupants=2, cooking_allowed=True, visitors_allowed=True,
                smoking_allowed=False, pets_allowed=False, approval_status="approved", submitted_at=now, reviewed_at=now, reviewed_by=owner)
            request = apps.get_model("rentals", "RentalRequest").objects.create(tenant=tenant, listing=listing, listing_revision=revision,
                preferred_move_in=today, total_occupancy=1, message="Historical request", status="accepted", responded_at=now)
            agreement = apps.get_model("rentals", "RentalAgreement").objects.create(rental_request=request, listing=listing,
                tenant=tenant, owner=owner, status="active", activated_at=now)
            terms = apps.get_model("rentals", "AgreementTerms").objects.create(agreement=agreement, version=1, listing_revision=revision,
                monthly_rent=10000, security_deposit=0, payment_due_day=5, total_occupancy=1, start_date=today,
                end_date=today+timedelta(days=3), additional_terms="Original terms", listing_snapshot={"title":"Original"},
                tenant_snapshot={"full_name":"Original tenant"}, owner_snapshot={"full_name":"Original owner"},
                sent_at=now, tenant_accepted_at=now, owner_accepted_at=now)
            type(agreement).objects.filter(pk=agreement.pk).update(current_terms=terms)
            executor = MigrationExecutor(connection)
            executor.migrate([target])
            record = RentalAgreement.objects.get(pk=agreement.pk)
            self.assertEqual(record.workflow_version, 1)
            self.assertEqual(record.status, "active")
            self.assertEqual(record.activated_at, now)
            self.assertEqual(record.current_terms.owner_accepted_at, now)
            self.assertEqual(record.current_terms.additional_terms, "Original terms")
            self.assertIsNone(record.current_terms.approved_at)
            self.assertEqual(AgreementReview.objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate([target])
