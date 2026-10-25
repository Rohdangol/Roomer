from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Permission
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import OwnerVerification, User
from listings.models import ListingRevision, RoomImage, RoomListing
from listings.services import change_listing_availability
from notifications.models import Notification
from .models import AgreementTerms, RentalAgreement, RentalRequest
from .agreement_services import (complete_agreement, confirm_agreement, finalize_agreement,
    prepare_agreement, send_agreement)
from .services import decide_request, submit_request


class RentalFixtures:
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="rental-owner", email="owner@rental.example", role="owner")
        cls.tenant = User.objects.create_user(username="rental-tenant", email="tenant@rental.example", role="tenant")
        cls.other = User.objects.create_user(username="rental-other", email="other@rental.example", role="tenant")
        cls.other_owner = User.objects.create_user(username="rental-other-owner", email="other-owner@rental.example", role="owner")
        for owner in (cls.owner, cls.other_owner):
            OwnerVerification.objects.create(user=owner, document_type="citizenship", document="unused.pdf", status="approved", submitted_at=timezone.now())
        cls.listing = RoomListing.objects.create(owner=cls.owner, listing_status="available")
        cls.revision = ListingRevision.objects.create(listing=cls.listing, version=1, title="Rental check room",
            description="Check room", city="Kathmandu", address="Check address", latitude="27.7", longitude="85.3",
            room_type="single_room", furnishing="furnished", monthly_rent="10000", security_deposit="5000",
            available_from=timezone.localdate(), maximum_occupants=2, cooking_allowed=True,
            visitors_allowed=True, smoking_allowed=False, pets_allowed=False, approval_status="approved",
            submitted_at=timezone.now(), reviewed_at=timezone.now(), reviewed_by=cls.owner)
        cls.listing.published_revision = cls.revision
        cls.listing.save()

    def submit(self, actor=None, **changes):
        details = dict(preferred_move_in=timezone.localdate(), total_occupancy=2, message="I would like to rent this room.")
        details.update(changes)
        return submit_request(actor or self.tenant, self.listing.pk, **details)


class RequestWorkflowTests(RentalFixtures, TestCase):
    def test_submission_and_recipient_scoped_notification(self):
        application = self.submit()
        self.assertEqual(application.listing_revision, self.revision)
        self.assertEqual(application.status, "pending")
        self.assertEqual(Notification.objects.get().user, self.owner)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("accounts:request_details", args=[application.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("accounts:request_cancel", args=[application.pk]), {"confirm": "on"}).status_code, 404)
        self.client.force_login(self.other_owner)
        self.assertEqual(self.client.get(reverse("accounts:owner_request_details", args=[application.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("accounts:owner_request_accept", args=[application.pk]), {"confirm": "on"}).status_code, 404)

    def test_date_capacity_message_and_eligibility_are_rechecked(self):
        for changes in ({"preferred_move_in": timezone.localdate() - timedelta(days=1)}, {"total_occupancy": 0}, {"total_occupancy": 3}, {"message": "  "}):
            with self.assertRaises(ValidationError):
                self.submit(**changes)
        ListingRevision.objects.filter(pk=self.revision.pk).update(available_from=timezone.localdate() + timedelta(days=2))
        with self.assertRaises(ValidationError):
            self.submit()
        RoomListing.objects.filter(pk=self.listing.pk).update(listing_status="inactive")
        with self.assertRaises(ValidationError):
            self.submit(preferred_move_in=timezone.localdate() + timedelta(days=3))
        self.assertEqual(RentalRequest.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_duplicate_constraint_and_pending_cancellation_reapplication(self):
        application = self.submit()
        with self.assertRaises(ValidationError):
            self.submit()
        with self.assertRaises(IntegrityError), transaction.atomic():
            RentalRequest.objects.create(tenant=self.tenant, listing=self.listing, listing_revision=self.revision,
                preferred_move_in=timezone.localdate(), total_occupancy=1, message="Duplicate")
        decide_request(self.tenant, application.pk, "cancel")
        replacement = self.submit()
        self.assertNotEqual(application.pk, replacement.pk)
        with self.assertRaises(ValidationError):
            decide_request(self.tenant, application.pk, "cancel")
        self.client.force_login(self.tenant)
        response = self.client.get(reverse("accounts:my_requests"))
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertEqual(response.context["status_filters"][0]["count"], 2)

    def test_decisions_require_owned_requests_and_reserve_once(self):
        application = self.submit()
        with self.assertRaises(RentalRequest.DoesNotExist):
            decide_request(self.other_owner, application.pk, "accept")
        with self.assertRaises(PermissionDenied):
            decide_request(self.tenant, application.pk, "accept")
        decide_request(self.owner, application.pk, "accept")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_status, "reserved")
        decide_request(self.owner, application.pk, "accept")
        self.assertEqual(RentalAgreement.objects.filter(rental_request=application).count(), 1)
        for actor, action in ((self.owner, "reject"), (self.tenant, "cancel")):
            with self.assertRaises(ValidationError):
                decide_request(actor, application.pk, action)
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertEqual(Notification.objects.filter(user=self.tenant).count(), 1)

    def test_post_csrf_confirmation_and_verification(self):
        application = self.submit()
        self.client.force_login(self.owner)
        url = reverse("accounts:owner_request_accept", args=[application.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {})
        application.refresh_from_db()
        self.assertEqual(application.status, "pending")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(url, {"confirm": "on"}).status_code, 403)
        OwnerVerification.objects.filter(user=self.owner).update(status="pending")
        self.assertRedirects(self.client.post(url, {"confirm": "on"}), reverse("accounts:verification"), fetch_redirect_response=False)
        application.refresh_from_db()
        self.assertEqual(application.status, "pending")

    def test_rejection_allows_new_application_and_accept_rechecks_listing(self):
        application = self.submit()
        decide_request(self.owner, application.pk, "reject")
        replacement = self.submit()
        RoomListing.objects.filter(pk=self.listing.pk).update(listing_status="inactive")
        with self.assertRaises(ValidationError):
            decide_request(self.owner, replacement.pk, "accept")
        replacement.refresh_from_db()
        self.assertEqual(replacement.status, "pending")


class AgreementFixtures(RentalFixtures):
    def agreement_details(self, start=None):
        start = start or timezone.localdate()
        return dict(monthly_rent="12000.00", security_deposit="4000.00", payment_due_day=5,
            start_date=start, end_date=start + timedelta(days=30), additional_terms="The terms supplied by the parties.")

    def ready_agreement(self, tenant=None, start=None):
        tenant = tenant or self.tenant
        application = self.submit(tenant)
        decide_request(self.owner, application.pk, "accept")
        agreement = prepare_agreement(self.owner, application.pk, self.agreement_details(start))
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        confirm_agreement(tenant, agreement.pk, agreement.current_terms_id)
        return agreement


class AgreementWorkflowTests(AgreementFixtures, TestCase):
    def test_reservation_blocks_pending_acceptance_and_database_conflicts(self):
        first = self.ready_agreement(start=timezone.localdate() + timedelta(days=2))
        second = self.ready_agreement(self.other)
        third_tenant = User.objects.create_user(username="third-tenant", email="third@rental.example")
        pending = self.submit(third_tenant)
        finalize_agreement(self.owner, first.pk, first.current_terms_id)
        with self.assertRaises(ValidationError):
            decide_request(self.owner, pending.pk, "accept")
        with self.assertRaises(ValidationError):
            finalize_agreement(self.owner, second.pk, second.current_terms_id)
        # The database also protects conflicting writes that bypass the service lock.
        with self.assertRaises(IntegrityError), transaction.atomic():
            RentalAgreement.objects.filter(pk=second.pk).update(status="active", activated_at=timezone.now())
        pending.refresh_from_db()
        self.assertEqual(pending.status, "pending")
        self.assertEqual(RentalAgreement.objects.filter(status="scheduled").count(), 1)

    def test_authorized_post_workflow_through_real_routes(self):
        self.client.force_login(self.tenant)
        create_url = reverse("accounts:request_create", args=[self.listing.pk])
        self.assertEqual(self.client.get(create_url).status_code, 200)
        self.client.post(create_url, {"preferred_move_in": timezone.localdate().isoformat(), "total_occupancy": 1,
            "message": "Please review my request.", "confirm": "on"})
        application = RentalRequest.objects.get()
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("accounts:owner_request_details", args=[application.pk]))
        self.assertEqual(detail.status_code, 200)
        self.client.post(reverse("accounts:owner_request_accept", args=[application.pk]), {"confirm": "on"})
        prepare_url = reverse("accounts:owner_agreement_prepare", args=[application.pk])
        self.assertContains(self.client.get(reverse("accounts:owner_request_details", args=[application.pk])), prepare_url)
        self.assertEqual(self.client.get(prepare_url).status_code, 200)
        details = self.agreement_details()
        response = self.client.post(prepare_url, {**details, "terms_id": "", "confirm": "on"})
        agreement = RentalAgreement.objects.get()
        self.assertRedirects(response, reverse("accounts:owner_agreement_details", args=[agreement.pk]))
        self.assertEqual(self.client.get(reverse("accounts:owner_agreements")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:owner")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:owner_profile")).status_code, 200)
        data = {"terms_id": agreement.current_terms_id, "confirm": "on"}
        self.client.post(reverse("accounts:owner_agreement_send", args=[agreement.pk]), data)
        self.client.force_login(self.tenant)
        self.assertContains(self.client.get(reverse("accounts:my_agreements")), "Pending")
        self.client.post(reverse("accounts:agreement_confirm", args=[agreement.pk]), data)
        self.client.force_login(self.owner)
        self.client.post(reverse("accounts:owner_agreement_finalize", args=[agreement.pk]), data)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "active")
        staff = User.objects.create_superuser(username="route-staff", email="route-staff@rental.example")
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse("accounts:admin_agreements") + "?status=active&q=" + str(agreement.pk)), "Rental check room")
        self.assertEqual(self.client.get(reverse("accounts:admin")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:admin_agreement_details", args=[agreement.pk])).status_code, 200)

    def test_historical_photos_require_participant_and_sent_version_access(self):
        with patch.object(RoomImage._meta.get_field("image"), "storage", InMemoryStorage()):
            photo = RoomImage.objects.create(revision=self.revision, position=1,
                image=SimpleUploadedFile("private.png", b"private-photo-content", content_type="image/png"))
            agreement = self.ready_agreement()
            request_photo_url = reverse("accounts:rental_photo", args=["request", agreement.rental_request_id, photo.pk])
            agreement_photo_url = reverse("accounts:rental_photo", args=["agreement", agreement.pk, photo.pk])
            self.client.force_login(self.tenant)
            for url in (request_photo_url, agreement_photo_url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"private-photo-content")
                self.assertEqual(response["Cache-Control"], "private, no-store")
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(request_photo_url).status_code, 404)
            self.assertEqual(self.client.get(agreement_photo_url).status_code, 404)
            staff = User.objects.create_user(username="photo-staff", email="photo-staff@rental.example", is_staff=True)
            staff.user_permissions.add(Permission.objects.get(codename="view_rentalagreement"))
            self.client.force_login(staff)
            self.assertEqual(self.client.get(agreement_photo_url).status_code, 403)

    def test_preparation_send_confirmation_and_immediate_activation(self):
        application = self.submit()
        decide_request(self.owner, application.pk, "accept")
        self.assertFalse(RentalAgreement.objects.exists())
        agreement = prepare_agreement(self.owner, application.pk, self.agreement_details())
        self.client.force_login(self.tenant)
        url = reverse("accounts:agreement_details", args=[agreement.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "12000.00")
        with self.assertRaises(ValidationError):
            finalize_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        confirm_agreement(self.tenant, agreement.pk, agreement.current_terms_id)
        finalize_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        agreement.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertEqual(agreement.status, "active")
        self.assertEqual(self.listing.listing_status, "occupied")
        self.assertEqual(Notification.objects.filter(title="Agreement finalized").count(), 2)
        self.assertEqual(Notification.objects.filter(title="Agreement activated").count(), 2)
        document = self.client.get(reverse("accounts:agreement_download", args=[agreement.pk]))
        self.assertEqual(document.status_code, 200)
        self.assertEqual(document["Cache-Control"], "private, no-store")

    def test_immutable_versions_and_stale_confirmation(self):
        agreement = self.ready_agreement()
        old_terms = agreement.current_terms
        old_terms.refresh_from_db()
        changed = self.agreement_details()
        changed["monthly_rent"] = "13500.00"
        revised = prepare_agreement(self.owner, agreement.rental_request_id, changed, old_terms.pk)
        self.assertEqual(revised.current_terms.version, 2)
        self.assertIsNone(revised.current_terms.tenant_accepted_at)
        old_terms.refresh_from_db()
        self.assertIsNotNone(old_terms.tenant_accepted_at)
        self.assertEqual(str(old_terms.monthly_rent), "12000.00")
        with self.assertRaises(ValidationError):
            old_terms.save()
        with self.assertRaises(ValidationError):
            finalize_agreement(self.owner, agreement.pk, old_terms.pk)
        self.client.force_login(self.tenant)
        response = self.client.get(reverse("accounts:agreement_details", args=[agreement.pk]))
        self.assertEqual(response.context["terms"].pk, old_terms.pk)
        self.assertNotContains(response, "13500.00")
        response = self.client.get(reverse("accounts:my_agreements"))
        self.assertNotContains(response, "13500.00")
        self.assertEqual(self.client.get(reverse("accounts:agreement_version", args=[agreement.pk, 2])).status_code, 404)
        send_agreement(self.owner, agreement.pk, revised.current_terms_id)
        with self.assertRaises(ValidationError):
            finalize_agreement(self.owner, agreement.pk, revised.current_terms_id)

    def test_due_days_dates_and_past_start_require_fresh_confirmation(self):
        application = self.submit()
        decide_request(self.owner, application.pk, "accept")
        for changes in ({"payment_due_day": 29}, {"payment_due_day": 0}, {"end_date": timezone.localdate()}, {"monthly_rent": "0.00"}, {"security_deposit": "-1.00"}):
            details = {**self.agreement_details(), **changes}
            with self.assertRaises(ValidationError):
                prepare_agreement(self.owner, application.pk, details)
        agreement = prepare_agreement(self.owner, application.pk, self.agreement_details())
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        confirm_agreement(self.tenant, agreement.pk, agreement.current_terms_id)
        with patch("rentals.agreement_services.local_today", return_value=timezone.localdate() + timedelta(days=1)):
            with self.assertRaisesMessage(ValidationError, "fresh Tenant confirmation"):
                finalize_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "pending")

    def test_scheduling_reserves_blocks_requests_and_command_is_idempotent(self):
        start = timezone.localdate() + timedelta(days=2)
        agreement = self.ready_agreement(start=start)
        finalize_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        agreement.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertEqual(agreement.status, "scheduled")
        self.assertEqual(self.listing.listing_status, "reserved")
        with self.assertRaises(ValidationError):
            self.submit(self.other)
        with self.assertRaises(ValidationError):
            change_listing_availability(self.owner, self.listing.pk, "deactivate")
        for day, expected in ((start - timedelta(days=1), "scheduled"), (start, "active"), (start, "active")):
            with patch("rentals.agreement_services.local_today", return_value=day), patch("rentals.management.commands.activate_scheduled_agreements.local_today", return_value=day):
                call_command("activate_scheduled_agreements", stdout=StringIO())
            agreement.refresh_from_db()
            self.assertEqual(agreement.status, expected)
        self.assertEqual(Notification.objects.filter(title="Agreement activated").count(), 2)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_status, "occupied")

    def test_participant_scope_admin_permissions_and_csrf(self):
        agreement = self.ready_agreement()
        for actor, route in ((self.other, "agreement_details"), (self.other_owner, "owner_agreement_details")):
            self.client.force_login(actor)
            self.assertEqual(self.client.get(reverse("accounts:" + route, args=[agreement.pk])).status_code, 404)
        staff = User.objects.create_user(username="rental-staff", email="staff@rental.example", is_staff=True)
        self.client.force_login(staff)
        url = reverse("accounts:admin_agreement_details", args=[agreement.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename="view_rentalagreement"))
        self.assertEqual(self.client.get(url).status_code, 200)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(reverse("accounts:owner_agreement_finalize", args=[agreement.pk]), {"confirm": "on", "terms_id": agreement.current_terms_id}).status_code, 403)
        self.client.force_login(self.owner)
        self.client.post(reverse("accounts:owner_agreement_finalize", args=[agreement.pk]), {"terms_id": agreement.current_terms_id})
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "pending")
        self.assertEqual(self.client.get(reverse("accounts:owner_agreement_finalize", args=[agreement.pk])).status_code, 405)

    def test_completion_requires_end_date_and_authorization_preserves_block(self):
        agreement = self.ready_agreement()
        finalize_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        with self.assertRaises(ValidationError):
            complete_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        with self.assertRaises(PermissionDenied):
            complete_agreement(self.tenant, agreement.pk, agreement.current_terms_id)
        staff = User.objects.create_user(username="completion-staff", email="completion@rental.example", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_rentalagreement"))
        with patch("rentals.agreement_services.local_today", return_value=agreement.current_terms.end_date):
            with self.assertRaises(PermissionDenied):
                complete_agreement(staff, agreement.pk, agreement.current_terms_id)
            staff.user_permissions.add(Permission.objects.get(codename="change_rentalagreement"))
            staff = User.objects.get(pk=staff.pk)  # Refresh Django's permission cache after the grant.
            RoomListing.objects.filter(pk=self.listing.pk).update(archived_at=timezone.now(), archived_by=staff, archive_source="admin")
            complete_agreement(staff, agreement.pk, agreement.current_terms_id)
        agreement.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertEqual(agreement.status, "completed")
        self.assertEqual(self.listing.listing_status, "inactive")
        self.assertEqual(self.listing.archive_source, "admin")
        self.assertEqual(Notification.objects.filter(title="Agreement completed").count(), 2)

    def test_completion_releases_at_exclusive_end_boundary(self):
        agreement = self.ready_agreement()
        finalize_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        end = agreement.current_terms.end_date
        with patch("rentals.agreement_services.local_today", return_value=end):
            complete_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_status, "available")
        next_agreement = self.ready_agreement(self.other, start=end)
        with patch("rentals.agreement_services.local_today", return_value=end):
            finalize_agreement(self.owner, next_agreement.pk, next_agreement.current_terms_id)
        next_agreement.refresh_from_db()
        self.assertEqual(next_agreement.status, "active")


class AgreementConflictTests(AgreementFixtures, TransactionTestCase):
    def setUp(self):
        self.setUpTestData()

    def test_concurrent_finalization_cannot_bind_two_agreements(self):
        if connection.vendor != "postgresql":
            self.skipTest("The production row-locking contract requires PostgreSQL.")
        first = self.ready_agreement()
        second = self.ready_agreement(self.other)
        barrier = Barrier(2)

        def finalize(pk, terms_id):
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.owner.pk)
                barrier.wait(timeout=10)
                try:
                    finalize_agreement(actor, pk, terms_id)
                    return "bound"
                except (ValidationError, IntegrityError):
                    return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(finalize, item.pk, item.current_terms_id) for item in (first, second)]
            results = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(results, ["bound", "conflict"])
        self.assertEqual(RentalAgreement.objects.filter(status="active").count(), 1)
        self.assertEqual(Notification.objects.filter(title="Agreement finalized").count(), 2)

    def test_concurrent_submission_has_one_pending_request(self):
        if connection.vendor != "postgresql":
            self.skipTest("The production row-locking contract requires PostgreSQL.")
        barrier = Barrier(2)

        def submit():
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.tenant.pk)
                barrier.wait(timeout=10)
                try:
                    self.submit(actor)
                    return "created"
                except (ValidationError, IntegrityError):
                    return "duplicate"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=20) for future in [pool.submit(submit), pool.submit(submit)]]
        self.assertCountEqual(results, ["created", "duplicate"])
        self.assertEqual(RentalRequest.objects.filter(status="pending").count(), 1)
