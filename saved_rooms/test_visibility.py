from io import BytesIO
from unittest.mock import patch

from PIL import Image
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from listings.models import RoomImage, RoomListing
from listings.services import tenant_readable_listings
from rentals.agreement_services import send_agreement
from rentals.test_consent_workflow import ConsentFixture
from .models import SavedRoom


class SavedVisibilityTests(ConsentFixture, TransactionTestCase):
    def setUp(self):
        type(self).setUpTestData()
        self.client.force_login(self.tenant)
        SavedRoom.objects.create(tenant=self.tenant, listing=self.listing)
        buffer = BytesIO()
        Image.new("RGB", (2, 2)).save(buffer, format="PNG")
        self.storage = InMemoryStorage()
        self.storage_patch = patch.object(RoomImage._meta.get_field("image"), "storage", self.storage)
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)
        self.photo = RoomImage.objects.create(revision=self.revision, position=1,
            image=SimpleUploadedFile("room.png", buffer.getvalue(), content_type="image/png"))

    def test_reserved_occupied_readable_but_requests_disabled_and_removal_works(self):
        for state in ("reserved", "occupied"):
            RoomListing.objects.filter(pk=self.listing.pk).update(listing_status=state)
            response = self.client.get(reverse("accounts:saved_rooms"))
            self.assertContains(response, self.revision.title)
            self.assertContains(response, state.title())
            self.assertContains(response, 'aria-label="Remove room from Saved Rooms"')
            detail = self.client.get(reverse("accounts:room_details", args=[self.listing.pk]))
            self.assertEqual(detail.status_code, 200)
            self.assertNotContains(detail, "data-request-modal-trigger")
            self.assertEqual(self.client.get(reverse("accounts:request_create", args=[self.listing.pk])).status_code, 404)
            photo = self.client.get(reverse("accounts:tenant_photo", args=[self.photo.pk]))
            self.assertEqual(photo.status_code, 200)
            photo.close()
        response = self.client.post(reverse("accounts:change_saved_room", args=[self.listing.pk]),
            {"action": "remove", "return_to": reverse("accounts:saved_rooms")})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SavedRoom.objects.filter(tenant=self.tenant).exists())

    def test_private_states_hide_current_content_and_scope_historical_summary(self):
        agreement = self.prepared(self.accepted())
        send_agreement(self.owner, agreement.pk, agreement.current_terms_id)
        RoomListing.objects.filter(pk=self.listing.pk).update(archived_at=timezone.now(),
            archived_by=self.owner, archive_source="admin")
        response = self.client.get(reverse("accounts:saved_rooms"))
        self.assertContains(response, "Historical summary from your agreement")
        self.assertContains(response, "Unavailable / restricted")
        self.assertContains(response, self.revision.title)
        self.assertFalse(tenant_readable_listings(self.tenant).exists())
        self.assertEqual(self.client.get(reverse("accounts:room_details", args=[self.listing.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("accounts:tenant_photo", args=[self.photo.pk])).status_code, 404)
        photo = self.client.get(reverse("accounts:rental_photo", args=["agreement", agreement.pk, self.photo.pk]))
        self.assertEqual(photo.status_code, 200)
        photo.close()
        SavedRoom.objects.create(tenant=self.other, listing=self.listing)
        self.client.force_login(self.other)
        response = self.client.get(reverse("accounts:saved_rooms"))
        self.assertNotContains(response, self.revision.title)
        self.assertNotContains(response, "Historical summary")
        self.assertEqual(self.client.get(reverse("accounts:rental_photo", args=["agreement", agreement.pk, self.photo.pk])).status_code, 404)
        RoomListing.objects.filter(pk=self.listing.pk).update(archived_at=None, archived_by=None, archive_source="", listing_status="inactive")
        response = self.client.get(reverse("accounts:saved_rooms"))
        self.assertContains(response, "Inactive / unpublished")
        self.assertNotContains(response, self.revision.title)
