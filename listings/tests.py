from datetime import date
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import OwnerVerification, User
from notifications.models import Notification
from .models import Amenity, ListingAmenity, ListingRevision, RoomImage, RoomListing
from .services import (add_listing_photo, change_listing_availability, create_listing, create_listing_draft, published_listings, remove_listing_photo, reorder_listing_photos, review_listing_revision, save_listing_draft, submit_listing_revision)
from .storage import validate_photo


def valid_details():
    return dict(title="Sunlit room", description="A quiet room.", city="Kathmandu", locality="Baneshwor", address="Test address", latitude="27.700000", longitude="85.300000", room_type="single_room", furnishing="furnished", monthly_rent="15000.00", security_deposit="5000.00", available_from=timezone.localdate(), maximum_occupants=2, cooking_allowed=True, visitors_allowed=True, smoking_allowed=False, pets_allowed=False)


def image_upload(format="PNG", extension="png", animated=False):
    output = BytesIO()
    image = Image.new("RGB", (4, 4), "white")
    if animated:
        image.save(output, format=format, save_all=True, append_images=[Image.new("RGB", (4, 4), "black")], duration=100)
    else:
        image.save(output, format=format)
    return SimpleUploadedFile(f"room.{extension}", output.getvalue())


class ListingWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="owner", email="owner@example.com", role="owner")
        cls.other = User.objects.create_user(username="other", email="other@example.com", role="owner")
        cls.tenant = User.objects.create_user(username="tenant", email="tenant@example.com")
        cls.reviewer = User.objects.create_superuser(username="admin", email="admin@example.com")
        OwnerVerification.objects.create(user=cls.owner, document_type="citizenship", document="existing.pdf", status="approved", submitted_at=timezone.now())

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = patch.object(RoomImage._meta.get_field("image"), "storage", FileSystemStorage(location=directory.name))
        storage.start()
        self.addCleanup(storage.stop)
        self.revision = create_listing(self.owner, **valid_details())
        self.listing = self.revision.listing

    def publish(self):
        add_listing_photo(self.owner, self.revision.pk, image_upload(), 1)
        submit_listing_revision(self.owner, self.revision.pk)
        review_listing_revision(self.reviewer, self.revision.pk, "approved")
        self.listing.refresh_from_db()
        self.revision.refresh_from_db()

    def test_first_approval_publishes_and_records_review_and_notification(self):
        self.assertEqual(published_listings().count(), 0)
        self.publish()
        self.assertEqual(self.listing.listing_status, "available")
        self.assertEqual(self.listing.published_revision_id, self.revision.pk)
        self.assertEqual(self.revision.reviewed_by, self.reviewer)
        self.assertIsNotNone(self.listing.published_at)
        self.assertEqual(list(published_listings()), [self.listing])
        self.assertEqual(Notification.objects.get(user=self.owner).user, self.owner)
        self.assertTrue(Notification.objects.filter(user=self.reviewer).exists())

    def test_pending_and_rejected_edits_keep_approved_content_and_photos(self):
        self.publish()
        old_file = self.revision.photos.get().image.name
        draft = create_listing_draft(self.owner, self.listing.pk)
        save_listing_draft(self.owner, draft.pk, {"monthly_rent": "18000.00"}, [Amenity.objects.get(name="Wi-Fi").pk])
        submit_listing_revision(self.owner, draft.pk)
        self.assertEqual(str(published_listings().get().published_revision.monthly_rent), "15000.00")
        review_listing_revision(self.reviewer, draft.pk, "rejected", "Revise the details.")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.published_revision_id, self.revision.pk)
        self.assertTrue(self.revision.photos.get().image.storage.exists(old_file))

    def test_approved_edit_does_not_reactivate_deactivated_listing(self):
        self.publish()
        draft = create_listing_draft(self.owner, self.listing.pk)
        submit_listing_revision(self.owner, draft.pk)
        change_listing_availability(self.owner, self.listing.pk, "deactivate")
        review_listing_revision(self.reviewer, draft.pk, "approved")
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_status, "inactive")
        self.assertEqual(self.listing.published_revision_id, draft.pk)
        self.assertEqual(published_listings().count(), 0)

    def test_archive_origin_restore_and_suspension_preserve_states(self):
        self.publish()
        change_listing_availability(self.reviewer, self.listing.pk, "archive")
        with self.assertRaises(PermissionDenied):
            change_listing_availability(self.owner, self.listing.pk, "restore")
        restored = change_listing_availability(self.reviewer, self.listing.pk, "restore")
        self.assertEqual(restored.listing_status, "inactive")
        change_listing_availability(self.owner, self.listing.pk, "activate")
        self.owner.is_active = False
        self.owner.save()
        self.assertEqual(published_listings().count(), 0)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.listing_status, "available")
        self.owner.is_active = True
        self.owner.save()
        self.assertEqual(published_listings().count(), 1)
        change_listing_availability(self.owner, self.listing.pk, "archive")
        self.assertEqual(published_listings().count(), 0)
        change_listing_availability(self.owner, self.listing.pk, "restore")
        self.assertEqual(published_listings().count(), 0)

    def test_every_occupied_listing_blocks_deactivation_and_archive(self):
        RoomListing.objects.filter(pk=self.listing.pk).update(listing_status="occupied")
        for actor in (self.owner, self.reviewer):
            for action in ("archive", "deactivate"):
                with self.assertRaises(ValidationError):
                    change_listing_availability(actor, self.listing.pk, action)

    def test_authorization_missing_photos_and_invalid_transitions(self):
        with self.assertRaises(PermissionDenied):
            create_listing(self.tenant, **valid_details())
        with self.assertRaises(PermissionDenied):
            save_listing_draft(self.other, self.revision.pk, {"title": "Stolen"})
        with self.assertRaises(ValidationError):
            submit_listing_revision(self.owner, self.revision.pk)
        with self.assertRaises(ValidationError):
            change_listing_availability(self.owner, self.listing.pk, "activate")
        add_listing_photo(self.owner, self.revision.pk, image_upload(), 1)
        OwnerVerification.objects.filter(user=self.owner).update(status="rejected")
        with self.assertRaises(PermissionDenied):
            submit_listing_revision(self.owner, self.revision.pk)
        OwnerVerification.objects.filter(user=self.owner).update(status="approved")
        submit_listing_revision(self.owner, self.revision.pk)
        with self.assertRaises(PermissionDenied):
            review_listing_revision(self.tenant, self.revision.pk, "approved")
        with self.assertRaises(ValidationError):
            review_listing_revision(self.reviewer, self.revision.pk, "rejected")
        review_listing_revision(self.reviewer, self.revision.pk, "approved")
        with self.assertRaises(ValidationError):
            review_listing_revision(self.reviewer, self.revision.pk, "approved")
        self.revision.refresh_from_db()
        self.revision.title = "Changed directly"
        with self.assertRaises(ValidationError):
            self.revision.save()
        with self.assertRaises(ValidationError):
            remove_listing_photo(self.owner, self.revision.photos.get().pk)

    def test_photo_limits_and_reordering(self):
        photos = [add_listing_photo(self.owner, self.revision.pk, image_upload(), position) for position in range(1, 11)]
        with self.assertRaises(ValidationError):
            add_listing_photo(self.owner, self.revision.pk, image_upload(), 11)
        reorder_listing_photos(self.owner, self.revision.pk, [photo.pk for photo in reversed(photos)])
        self.assertEqual(self.revision.photos.first().image.name, photos[-1].image.name)

    def test_database_constraints_and_protected_history(self):
        for changes in ({"monthly_rent": 0}, {"security_deposit": -1}, {"latitude": 91}, {"room_type": "studio"}, {"maximum_occupants": 0}, {"quiet_hours_start": "10:00"}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                ListingRevision.objects.filter(pk=self.revision.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Amenity.objects.create(name="wi-fi")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoomListing.objects.filter(pk=self.listing.pk).update(archive_source="admin")
        with self.assertRaises(ProtectedError):
            self.owner.delete()
        with self.assertRaises(ProtectedError):
            self.listing.delete()
        link = ListingAmenity.objects.create(revision=self.revision, amenity=Amenity.objects.first())
        with self.assertRaises(IntegrityError), transaction.atomic():
            ListingAmenity.objects.create(revision=self.revision, amenity=link.amenity)
        with self.assertRaises(ValidationError):
            create_listing_draft(self.owner, self.listing.pk)

    def test_cross_listing_publication_pointer_is_rejected(self):
        self.publish()
        other_listing = create_listing(self.other, **valid_details()).listing
        other_listing.published_revision = self.revision
        with self.assertRaises(ValidationError):
            other_listing.full_clean()

    def test_failed_notification_rolls_back_approval(self):
        add_listing_photo(self.owner, self.revision.pk, image_upload(), 1)
        submit_listing_revision(self.owner, self.revision.pk)
        existing_notice_ids = set(Notification.objects.values_list("pk", flat=True))
        with patch("listings.services.create_notification", side_effect=ValidationError("Notification failed")):
            with self.assertRaises(ValidationError):
                review_listing_revision(self.reviewer, self.revision.pk, "approved")
        self.listing.refresh_from_db()
        self.revision.refresh_from_db()
        self.assertIsNone(self.listing.published_revision_id)
        self.assertEqual(self.revision.approval_status, "pending")
        self.assertEqual(set(Notification.objects.values_list("pk", flat=True)), existing_notice_ids)
        self.assertFalse(Notification.objects.filter(user=self.owner).exists())

    def test_pending_uniqueness_and_draft_update_rollback(self):
        self.publish()
        draft = create_listing_draft(self.owner, self.listing.pk)
        with self.assertRaises(ValidationError):
            save_listing_draft(self.owner, draft.pk, {"title": "Should roll back"}, [999999])
        draft.refresh_from_db()
        self.assertEqual(draft.title, self.revision.title)
        submit_listing_revision(self.owner, draft.pk)
        next_draft = create_listing_draft(self.owner, self.listing.pk)
        submit_listing_revision(self.owner, next_draft.pk)
        draft.refresh_from_db()
        self.assertEqual(draft.approval_status, "superseded")
        self.assertEqual(self.listing.revisions.filter(approval_status="pending").count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ListingRevision.objects.filter(pk=draft.pk).update(approval_status="pending", submitted_at=timezone.now())

    def test_admin_records_are_read_only(self):
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse("admin:listings_roomlisting_change", args=[self.listing.pk]))
        self.assertEqual(response.status_code, 200)
        model_admin = admin.site._registry[RoomListing]
        self.assertFalse(model_admin.has_change_permission(response.wsgi_request, self.listing))


class PhotoValidationTests(TestCase):
    def test_supported_formats_are_decoded(self):
        for format, extension in (("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")):
            validate_photo(image_upload(format, extension))

    def test_fake_mismatched_animated_and_large_images_are_rejected(self):
        for photo in (
            SimpleUploadedFile("fake.png", b"\x89PNG\r\n\x1a\ninvalid"),
            SimpleUploadedFile("vector.svg", b"<svg/>"),
            image_upload("PNG", "jpg"),
            image_upload("PNG", "png", animated=True),
            image_upload("WEBP", "webp", animated=True),
            SimpleUploadedFile("large.jpg", b"x" * (5 * 1024 * 1024 + 1)),
        ):
            with self.subTest(photo=photo.name), self.assertRaises(ValidationError):
                validate_photo(photo)
