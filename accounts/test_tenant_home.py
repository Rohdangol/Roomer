from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from listings.models import RoomImage
from listings.services import (add_listing_photo, change_listing_availability, create_listing, create_listing_draft, review_listing_revision, save_listing_draft, submit_listing_revision)
from listings.tests import image_upload, valid_details
from .models import OwnerVerification, User


class TenantHomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = User.objects.create_user(username="tenant", email="tenant@example.com")
        cls.owner = User.objects.create_user(username="owner", email="owner@example.com", role="owner")
        cls.admin = User.objects.create_superuser(username="admin", email="admin@example.com")
        OwnerVerification.objects.create(user=cls.owner, document_type="citizenship", document="existing.pdf", submitted_at=timezone.now(), status="approved")

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        storage = patch.object(RoomImage._meta.get_field("image"), "storage", FileSystemStorage(location=directory.name))
        storage.start()
        self.addCleanup(storage.stop)
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        self.url = reverse("accounts:tenant")

    def publish_room(self, title="A real room", locality="Baneshwor", city="Kathmandu", rent="15000.00"):
        details = valid_details()
        details.update(title=title, locality=locality, city=city, monthly_rent=rent)
        revision = create_listing(self.owner, **details)
        photo = add_listing_photo(self.owner, revision.pk, image_upload(), 1)
        submit_listing_revision(self.owner, revision.pk)
        review_listing_revision(self.admin, revision.pk, "approved")
        return revision, photo

    def test_empty_state_and_disabled_future_actions(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, "accounts/tenant_home.html")
        self.assertTemplateUsed(response, "accounts/base_role.html")
        for text in ("No rooms available yet", "Recommended Rooms", "Fresh on Roomer", "Browse by Neighbourhood", "Personalized recommendations are not available yet", "Roommate discovery is outside"):
            self.assertContains(response, text)
        self.assertContains(response, 'type="button" disabled')
        self.assertNotContains(response, 'href="#"')
        self.assertNotContains(response, "Verified")
        self.assertEqual(response.context["latest_rooms"], [])

    def test_latest_three_cards_and_real_neighbourhood_counts(self):
        for index in range(4):
            self.publish_room(title=f"Room number {index}")
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["latest_rooms"]), 3)
        self.assertEqual([listing.published_revision.title for listing in response.context["latest_rooms"]], ["Room number 3", "Room number 2", "Room number 1"])
        self.assertEqual(response.context["neighbourhoods"][0]["room_count"], 4)
        self.assertContains(response, "4 available rooms")
        self.assertNotContains(response, "Room number 0")

    def test_location_search_and_area_shortcuts_use_published_fields(self):
        self.publish_room("Kathmandu room", "Baneshwor", "Kathmandu")
        self.publish_room("Lalitpur room", "Patan", "Lalitpur")
        response = self.client.get(self.url, {"q": "  patan  "})
        self.assertEqual(response.context["query"], "patan")
        self.assertContains(response, "Lalitpur room")
        self.assertNotContains(response, "Kathmandu room")
        response = self.client.get(self.url, {"area": "Baneshwor", "city": "Kathmandu"})
        self.assertContains(response, "Kathmandu room")
        self.assertNotContains(response, "Lalitpur room")
        response = self.client.get(self.url, {"q": "No such area"})
        self.assertContains(response, "No rooms match this location")

    def test_unpublished_archived_inactive_and_suspended_rooms_are_hidden(self):
        draft = create_listing(self.owner, **valid_details())
        self.assertEqual(self.client.get(self.url).context["latest_rooms"], [])
        revision, photo = self.publish_room()
        for action in ("deactivate", "archive"):
            change_listing_availability(self.owner, revision.listing_id, action)
            self.assertEqual(self.client.get(self.url).context["latest_rooms"], [])
            self.assertEqual(self.client.get(reverse("accounts:tenant_photo", args=[photo.pk])).status_code, 404)
            if action == "archive":
                change_listing_availability(self.owner, revision.listing_id, "restore")
            change_listing_availability(self.owner, revision.listing_id, "activate")
        self.owner.is_active = False
        self.owner.save()
        self.assertEqual(self.client.get(self.url).context["neighbourhoods"], [])
        self.assertEqual(self.client.get(reverse("accounts:tenant_photo", args=[photo.pk])).status_code, 404)

    def test_pending_revision_and_photos_never_replace_public_snapshot(self):
        revision, approved_photo = self.publish_room("Approved title")
        draft = create_listing_draft(self.owner, revision.listing_id)
        save_listing_draft(self.owner, draft.pk, {"title": "Private pending title", "monthly_rent": "99999.00"})
        private_photo = add_listing_photo(self.owner, draft.pk, image_upload(), 2)
        submit_listing_revision(self.owner, draft.pk)
        response = self.client.get(self.url)
        self.assertContains(response, "Approved title")
        self.assertNotContains(response, "Private pending title")
        self.assertNotContains(response, "99999")
        self.assertEqual(self.client.get(reverse("accounts:tenant_photo", args=[private_photo.pk])).status_code, 404)
        response = self.client.get(reverse("accounts:tenant_photo", args=[approved_photo.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        review_listing_revision(self.admin, draft.pk, "approved")
        self.assertEqual(self.client.get(reverse("accounts:tenant_photo", args=[approved_photo.pk])).status_code, 404)

    def test_tenant_only_access_for_home_and_photos(self):
        revision, photo = self.publish_room()
        photo_url = reverse("accounts:tenant_photo", args=[photo.pk])
        for user in (self.owner, self.admin):
            self.client.force_login(user, backend="accounts.backends.EmailBackend")
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.get(photo_url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.get(photo_url).status_code, 302)

    def test_cards_escape_user_content(self):
        self.publish_room("<script>alert('title')</script>")
        response = self.client.get(self.url)
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert")

    def test_card_price_preserves_actual_decimal_amount(self):
        self.publish_room(rent="15000.75")
        self.assertContains(self.client.get(self.url), "Rs 15000.75")
