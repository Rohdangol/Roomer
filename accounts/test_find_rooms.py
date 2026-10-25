from django.test import TestCase
from django.urls import reverse

from listings.models import Amenity
from listings.services import create_listing, create_listing_draft, save_listing_draft, change_listing_availability
from listings.tests import valid_details
from . import test_tenant_home as home_tests


class FindRoomsTests(TestCase):
    setUpTestData = classmethod(home_tests.TenantHomeTests.setUpTestData.__func__)
    setUp = home_tests.TenantHomeTests.setUp
    publish_room = home_tests.TenantHomeTests.publish_room

    def results(self, **parameters):
        # Simulate an explicit combobox/map selection; never contact a public provider.
        from accounts.search_location import signed_place
        if parameters.get("q") and "latitude" not in parameters:
            parameters = {**signed_place({"label": parameters["q"].strip(), "latitude": 27.7, "longitude": 85.3}), **parameters}
            parameters["q"] = parameters["q"].strip()
        elif "latitude" in parameters:
            parameters.setdefault("point_source", "map")
            parameters.setdefault("point_location", parameters.get("q", ""))
        return self.client.get(reverse("accounts:find_rooms"), parameters)

    def test_location_budget_and_choices(self):
        self.publish_room("Affordable", "Patan", "Lalitpur", "15000.75")
        self.publish_room("Expensive", "Patan", "Lalitpur", "20000")
        response = self.results(q="  PATAN  ", max_budget="15000.75", room_type="single_room", furnishing="furnished")
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertContains(response, "Affordable")
        self.assertContains(response, "Expensive")
        self.assertEqual(self.results(area="Patan", city="Other").context["page_obj"].paginator.count, 2)
        self.assertEqual(self.results(room_type="2bhk").context["page_obj"].paginator.count, 2)
        self.assertEqual(self.results(furnishing="unfurnished").context["page_obj"].paginator.count, 2)

    def test_invalid_filters_are_visible_and_do_not_broaden_results(self):
        self.publish_room()
        for parameters in ({"max_budget": "-1"}, {"max_budget": "NaN"}, {"max_budget": "999999999999999999"}, {"room_type": "invalid"}, {"furnishing": "invalid"}, {"amenities": ["999999"]}, {"q": "a" * 256}):
            response = self.results(**parameters)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertEqual(response.context["page_obj"].paginator.count, 1)
            self.assertEqual(response.context["recommended_rooms"], [])

    def test_all_selected_amenities_and_published_snapshot_only(self):
        first, second = list(Amenity.objects.all()[:2])
        revision, _ = self.publish_room()
        # A newer private draft must not satisfy public filters.
        draft = create_listing_draft(self.owner, revision.listing_id)
        save_listing_draft(self.owner, draft.pk, {}, amenity_ids=[first.pk, second.pk])
        self.assertEqual(self.results(amenities=[first.pk]).context["page_obj"].paginator.count, 1)
        from listings.services import submit_listing_revision, review_listing_revision
        submit_listing_revision(self.owner, draft.pk)
        review_listing_revision(self.admin, draft.pk, "approved")
        self.assertEqual(self.results(amenities=[first.pk, second.pk]).context["page_obj"].paginator.count, 1)
        third = Amenity.objects.exclude(pk__in=[first.pk, second.pk]).first()
        self.assertEqual(self.results(amenities=[first.pk, third.pk]).context["page_obj"].paginator.count, 1)

    def test_pagination_preserves_filters_and_handles_bad_pages(self):
        for index in range(5):
            self.publish_room(title=f"Room {index}")
        response = self.results(q="Baneshwor", max_budget="16000", room_type="single_room", page="1")
        self.assertEqual(len(response.context["page_obj"]), 4)
        self.assertEqual(response.context["page_obj"].paginator.count, 5)
        self.assertIn("q=Baneshwor", response.context["pagination_query"])
        self.assertIn("max_budget=16000", response.context["pagination_query"])
        self.assertContains(response, "page=2")
        self.assertEqual(len(self.results(q="Baneshwor", page="2").context["page_obj"]), 1)
        for page in ("bad", "999", "-2"):
            self.assertEqual(self.results(page=page).status_code, 200)

    def test_visibility_and_access(self):
        create_listing(self.owner, **valid_details())
        revision, _ = self.publish_room()
        change_listing_availability(self.owner, revision.listing_id, "deactivate")
        self.assertEqual(self.results().context["page_obj"].paginator.count, 0)
        change_listing_availability(self.owner, revision.listing_id, "activate")
        change_listing_availability(self.owner, revision.listing_id, "archive")
        self.assertEqual(self.results().context["page_obj"].paginator.count, 0)
        change_listing_availability(self.owner, revision.listing_id, "restore")
        change_listing_availability(self.owner, revision.listing_id, "activate")
        self.owner.is_active = False
        self.owner.save()
        self.assertEqual(self.results().context["page_obj"].paginator.count, 0)
        for user in (self.owner, self.admin):
            user.is_active = True
            user.save()
            self.client.force_login(user, backend="accounts.backends.EmailBackend")
            self.assertEqual(self.results().status_code, 403)
        self.client.logout()
        self.assertEqual(self.results().status_code, 302)

    def test_home_and_navigation_link_to_find_rooms(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'action="' + reverse("accounts:tenant") + '"')
        response = self.results()
        self.assertContains(response, 'href="' + reverse("accounts:find_rooms") + '?initial=preferences" aria-current="page"')
        self.assertContains(response, 'id="room-location-map"')
        self.assertContains(response, "0 results found")

    def test_nearby_radii_combined_filters_and_pagination(self):
        from listings.services import add_listing_photo, submit_listing_revision, review_listing_revision
        from listings.tests import image_upload
        # At the equator 0.01 longitude degrees is about 1.112 km.
        for index, longitude in enumerate(("0", "0.008", "0.015", "0.018", "0.019", "0.03", "0.06")):
            details = valid_details()
            details.update(latitude="0", longitude=longitude, title=f"Distance room {index}")
            revision = create_listing(self.owner, **details)
            add_listing_photo(self.owner, revision.pk, image_upload(), 1)
            submit_listing_revision(self.owner, revision.pk)
            review_listing_revision(self.admin, revision.pk, "approved")
        for radius, expected in ((1, 2), (2, 3), (5, 6)):
            response = self.results(latitude="0", longitude="0", radius=radius)
            self.assertEqual(response.context["page_obj"].paginator.count, 7)
            self.assertEqual(len(response.context["recommended_rooms"]), expected)
        response = self.results(latitude="0", longitude="0")
        self.assertEqual(response.context["page_obj"].paginator.count, 7)
        self.assertEqual(self.results().context["page_obj"].paginator.count, 7)
        response = self.results(latitude="0", longitude="0", radius=5, page=2)
        self.assertEqual(len(response.context["page_obj"]), 3)
        self.assertIn("latitude=0", response.context["pagination_query"])
        self.assertContains(response, "page=1")
        self.assertEqual(self.results(latitude="0", longitude="0", radius=5, max_budget=100).context["page_obj"].paginator.count, 7)
        self.assertEqual(self.results(latitude="0", longitude="0", radius=5, q="Patan").context["page_obj"].paginator.count, 7)

    def test_coordinate_and_radius_validation(self):
        for parameters in ({"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": -181}, {"latitude": "NaN", "longitude": 0}, {"latitude": "inf", "longitude": 0}, {"latitude": 0}, {"longitude": 0}, {"radius": 3}, {"radius": "invalid"}):
            response = self.results(**parameters)
            self.assertTrue(response.context["form"].errors, parameters)
            self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_nearby_still_hides_ineligible_listings(self):
        revision, _ = self.publish_room()
        response = self.results(latitude="27.7", longitude="85.3", radius=2)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        change_listing_availability(self.owner, revision.listing_id, "deactivate")
        self.assertEqual(self.results(latitude="27.7", longitude="85.3", radius=2).context["page_obj"].paginator.count, 0)
