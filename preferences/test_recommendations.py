"""Focused algorithm checks; all records exist only in Django's test database."""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import OwnerVerification, User
from listings.models import ListingRevision, RoomListing
from listings.tests import valid_details
from .models import TenantPreference
from .recommendations import recommend_rooms, score_room


class FactorChecks(SimpleTestCase):
    def test_approved_formulas(self):
        preference = SimpleNamespace(preferred_location="Sanepa", maximum_budget=Decimal("10000"),
            preferred_room_type="single_room", preferred_furnishing="furnished", latitude=None, longitude=None)
        revision = SimpleNamespace(locality="Different nearby locality", city="Kathmandu", address="Road",
            monthly_rent=Decimal("10000"), room_type="single_room", furnishing="furnished")
        def score(preferred, amenities, distance=1.0):
            return score_room(preference, revision, preferred, amenities, distance_km=distance, radius=2)
        self.assertEqual(score({1, 2}, {1, 2})["percentage"], 100)
        self.assertEqual(score(set(), set())["factors"]["location"], 1)
        revision.monthly_rent = Decimal("20000")
        # Previously 55% with a text mismatch; geographical L restores 30 points.
        self.assertEqual(score({1, 2}, {1, 2})["percentage"], 85)
        result = score({1, 2}, {1})
        self.assertEqual(result["factors"]["budget"], Decimal("0.5"))
        self.assertEqual(result["factors"]["amenities"], Decimal("0.5"))
        self.assertEqual(result["score"], Decimal("0.775"))
        self.assertEqual(result["breakdown"][0]["detail"], "Within your selected area")
        self.assertIn("Above budget", result["explanation"])
        preference.preferred_furnishing = "any"
        revision.furnishing = "unfurnished"
        self.assertEqual(score(set(), set())["factors"]["furnishing"], 1)
        self.assertEqual(score(set(), set())["factors"]["amenities"], 1)
        self.assertIsNotNone(score(set(), set(), distance=2))
        self.assertIsNone(score(set(), set(), distance=2.000001))
        self.assertIsNone(score(set(), set(), distance=None))


class RecommendationIntegrationChecks(TestCase):
    def selection(self, name="Baneshwor", **values):
        from accounts.search_location import signed_place
        return {**signed_place({"label": name, "latitude": 27.7, "longitude": 85.3}), **values}

    def setUp(self):
        from unittest.mock import patch
        # Existing text-only checks must not contact the public lookup provider.
        lookup = patch("accounts.search_location.lookup_text_location", return_value=({"results": []}, 200))
        self.lookup = lookup.start()
        self.addCleanup(lookup.stop)
        boundary_lookup = patch("preferences.recommendations.lookup_text_location", return_value=({"results": [
            {"latitude": 27.7, "longitude": 85.3}]}, 200))
        self.boundary_lookup = boundary_lookup.start()
        self.addCleanup(boundary_lookup.stop)

    @classmethod
    def setUpTestData(cls):
        cls.tenant = User.objects.create_user(username="rec-tenant", email="rec-tenant@example.test")
        cls.owner = User.objects.create_user(username="rec-owner", email="rec-owner@example.test", role="owner")
        cls.reviewer = User.objects.create_superuser(username="rec-reviewer", email="rec-reviewer@example.test")
        OwnerVerification.objects.create(user=cls.owner, document_type="citizenship", document="test-only.pdf",
            submitted_at=timezone.now(), status="approved")
        cls.preference = TenantPreference.objects.create(tenant=cls.tenant, preferred_location="Baneshwor",
            maximum_budget=10000, preferred_room_type="single_room", preferred_furnishing="any")

    def room(self, status="available", approval="approved", rent="10000", room_type="single_room"):
        listing = RoomListing.objects.create(owner=self.owner, listing_status=status, published_at=timezone.now())
        details = valid_details()
        details.update(monthly_rent=rent, room_type=room_type)
        revision = ListingRevision.objects.create(listing=listing, version=1, approval_status=approval,
            submitted_at=timezone.now(), reviewed_at=timezone.now() if approval == "approved" else None,
            reviewed_by=self.reviewer if approval == "approved" else None, **details)
        listing.published_revision = revision
        listing.save(update_fields=["published_revision"])
        return listing

    def test_visibility_order_and_batched_queries(self):
        first = self.room()
        second = self.room()
        RoomListing.objects.filter(pk__in=[first.pk, second.pk]).update(published_at=first.published_at)
        cheaper_type_mismatch = self.room(room_type="double_room")
        above_budget = self.room(rent="20000")
        for status in ("reserved", "occupied", "inactive"):
            self.room(status=status)
        self.room(approval="pending")
        archived = self.room()
        RoomListing.objects.filter(pk=archived.pk).update(archived_at=timezone.now(), archived_by=self.owner, archive_source="owner")
        # Preference amenities + candidates + photo prefetch + amenity prefetch, independent of room count.
        with self.assertNumQueries(4):
            matches = recommend_rooms(self.tenant, self.preference, limit=20)
        self.assertEqual([room.pk for room in matches], [second.pk, first.pk, above_budget.pk, cheaper_type_mismatch.pk])
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertEqual(recommend_rooms(self.tenant, self.preference), [])
        self.owner.is_active = True
        self.owner.save(update_fields=["is_active"])
        OwnerVerification.objects.filter(user=self.owner).update(status="rejected")
        self.assertEqual(recommend_rooms(self.tenant, self.preference), [])

    def test_navbar_and_repeated_search_use_identical_context(self):
        self.room()
        self.room(rent="20000", room_type="double_room")
        far = self.room()
        ListingRevision.objects.filter(pk=far.published_revision_id).update(latitude="28.200000")
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:find_rooms")
        label = "Sanepa, Lalitpur, Lalitpur-02, Bagmati Province, Nepal"
        for saved_point in (True, False):
            with self.subTest(saved_point=saved_point):
                TenantPreference.objects.filter(pk=self.preference.pk).update(
                    preferred_location=label, latitude="27.700000" if saved_point else None,
                    longitude="85.300000" if saved_point else None)
                self.lookup.reset_mock()
                self.lookup.return_value = ({"results": [{"label": label, "latitude": 27.7, "longitude": 85.3}]}, 200)
                initial = self.client.get(url, {"initial": "preferences", "latitude": "", "longitude": "", "radius": ""}, follow=True)
                if saved_point:
                    self.lookup.assert_not_called()
                else:
                    self.lookup.assert_called_once_with(label, "")
                filters = initial.context["form"].cleaned_data
                self.assertEqual(filters["latitude"], 27.7)
                self.assertEqual(filters["longitude"], 85.3)
                self.assertEqual(filters["radius"], 2)
                repeated = self.client.get(url, self.selection(label, radius="2", max_budget="10000",
                    room_type="single_room", furnishing=""))
                matches = lambda response: [(room.pk, room.recommendation["score"])
                    for room in response.context["recommended_rooms"]]
                self.assertEqual(len(matches(initial)), 2)
                self.assertEqual(matches(initial), matches(repeated))
                self.assertNotIn(far.pk, [pk for pk, score in matches(initial)])
                self.preference.refresh_from_db()
                self.assertEqual(self.preference.preferred_location, label)
                self.assertEqual(self.preference.latitude is not None, saved_point)

    def test_saved_location_lifecycle_from_rendered_navbar(self):
        from accounts.search_location import selected_location
        from urllib.parse import parse_qs, urlsplit
        self.room()
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:find_rooms")
        profile_url = reverse("accounts:tenant_profile")
        selection = self.selection("Sanepa, Lalitpur")
        self.lookup.return_value = ({"results": [
            {"label": "Sanepa, Lalitpur", "latitude": 27.7, "longitude": 85.3},
            {"label": "Sanepa, Other city", "latitude": 28.2, "longitude": 84.0}]}, 200)
        home = self.client.get(reverse("accounts:tenant"))
        self.assertContains(home, 'href="' + url + '?initial=preferences"')
        initial = self.client.get(url, {"initial": "preferences"}, follow=True)
        self.assertTrue(initial.context["setup_location"])
        self.assertFalse(initial.context["form"].errors)
        self.assertContains(initial, "Your saved location needs a map point")
        self.assertEqual(len(initial.context["location_choices"]), 2)
        before = (self.preference.maximum_budget, self.preference.preferred_room_type,
            self.preference.preferred_furnishing)
        saved = self.client.post(url, {**selection, "setup_location": "1"})
        self.assertEqual(saved.status_code, 302, saved.context and (saved.context["setup_error"], saved.context["form"].errors))
        self.preference.refresh_from_db()
        self.assertEqual(float(self.preference.latitude), 27.7)
        self.assertEqual(before, (self.preference.maximum_budget, self.preference.preferred_room_type,
            self.preference.preferred_furnishing))
        self.lookup.reset_mock()
        restored = self.client.get(url, {"initial": "preferences"}, follow=True)
        self.lookup.assert_not_called()
        self.assertEqual(len(restored.context["recommended_rooms"]), 1)
        params = {name: values[-1] for name, values in parse_qs(urlsplit(restored.redirect_chain[-1][0]).query).items()}
        self.assertTrue(selected_location(params))
        self.assertEqual(restored.context["form"].cleaned_data["radius"], 2)
        profile = self.client.get(profile_url)
        self.assertContains(profile, "data-location-search")
        self.assertTrue(profile.context["preference_form"].fields["latitude"].widget.is_hidden)
        values = {**selection, "preferred_location": selection["q"], "maximum_budget": "12000",
            "preferred_room_type": "double_room", "preferred_furnishing": "furnished"}
        self.assertEqual(self.client.post(profile_url, {**values, "action": "preferences"}).status_code, 302)
        self.preference.refresh_from_db()
        self.assertEqual(float(self.preference.longitude), 85.3)
        # First-search onboarding uses the same form/service, not a redirect-only point.
        TenantPreference.objects.filter(pk=self.preference.pk).delete()
        self.assertEqual(self.client.post(reverse("accounts:tenant"), values).status_code, 302)
        preference = TenantPreference.objects.get(tenant=self.tenant)
        self.assertEqual(float(preference.latitude), 27.7)
        self.client.get(url, self.selection("Another search"))
        preference.refresh_from_db()
        self.assertEqual(preference.preferred_location, "Sanepa, Lalitpur")

    def test_profile_location_change_requires_selection_and_restores_navbar_point(self):
        from accounts.search_location import signed_place, selected_location
        from urllib.parse import parse_qs, urlsplit
        TenantPreference.objects.filter(pk=self.preference.pk).update(
            preferred_location="Sanepa, Lalitpur", latitude="27.681629", longitude="85.310761")
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:tenant_profile")
        profile = self.client.get(url)
        form = profile.context["preference_form"]
        self.assertTrue(selected_location({**form.initial, "q": form.initial["preferred_location"]}))
        values = {"action": "preferences", "preferred_location": "Kirtipur, Kathmandu",
            "maximum_budget": "18000", "preferred_room_type": "double_room", "preferred_furnishing": "furnished"}
        invalid = self.client.post(url, values)
        self.assertContains(invalid, "Choose a location from the suggestions before saving a changed location.")
        self.assertEqual(invalid.context["preference_form"]["maximum_budget"].value(), "18000")
        self.preference.refresh_from_db()
        self.assertEqual(self.preference.preferred_location, "Sanepa, Lalitpur")
        unchanged = self.client.post(url, {**values, "preferred_location": "Sanepa, Lalitpur"})
        self.assertEqual(unchanged.status_code, 302)
        self.preference.refresh_from_db()
        self.assertEqual(self.preference.latitude, Decimal("27.681629"))
        point = signed_place({"label": "Kirtipur, Kathmandu", "latitude": 27.678, "longitude": 85.277})
        self.assertEqual(self.client.post(url, {**values, **point}).status_code, 302)
        self.lookup.reset_mock()
        restored = self.client.get(reverse("accounts:find_rooms"), {"initial": "preferences"}, follow=True)
        self.lookup.assert_not_called()
        filters = restored.context["form"].cleaned_data
        self.assertEqual((filters["latitude"], filters["longitude"], filters["radius"]), (27.678, 85.277, 2))
        self.assertEqual((filters["max_budget"], filters["room_type"], filters["furnishing"]),
            (Decimal("18000"), "double_room", "furnished"))
        parameters = {key: value[-1] for key, value in parse_qs(urlsplit(restored.redirect_chain[-1][0]).query).items()}
        self.assertTrue(selected_location(parameters))
        self.assertFalse(restored.context["location_required"])

    def test_home_complete_and_incomplete_preferences(self):
        self.room()
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        response = self.client.get(reverse("accounts:tenant"))
        self.assertContains(response, "100% Preference match")
        self.assertEqual(response.context["recommended_rooms"][0].recommendation["factors"]["location"], 1)
        TenantPreference.objects.filter(pk=self.preference.pk).delete()
        response = self.client.get(reverse("accounts:tenant"))
        self.assertContains(response, "Complete Preferences")
        self.assertNotContains(response, "% match")

    def test_find_rooms_scores_applied_filters_and_preserves_catalogue(self):
        from listings.models import Amenity, ListingAmenity
        wifi = Amenity.objects.create(name="Focused test Wi-Fi")
        exact = self.room()
        ListingAmenity.objects.create(revision=exact.published_revision, amenity=wifi)
        partial = self.room(rent="20000", room_type="double_room")
        hidden = self.room(status="reserved")
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:find_rooms")
        response = self.client.get(url, self.selection(max_budget="10000", room_type="single_room", amenities=[wifi.pk]))
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertEqual(response.context["page_obj"][0].pk, partial.pk)
        matches = response.context["recommended_rooms"]
        self.assertEqual([room.pk for room in matches], [exact.pk, partial.pk])
        self.assertEqual(matches[0].recommendation["percentage"], 100)
        self.assertEqual(matches[1].recommendation["factors"]["amenities"], 0)
        self.assertNotIn(hidden.pk, [room.pk for room in matches])
        self.assertContains(response, "Ranked for your search. Some preferences may differ.")
        response = self.client.get(url, self.selection("Sanepa", room_type="2bhk"))
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertEqual(response.context["recommended_rooms"][0].pk, partial.pk)
        self.assertEqual(response.context["recommended_rooms"][0].recommendation["percentage"], 85)
        self.assertContains(response, "Browse all available rooms across all locations.")
        self.preference.refresh_from_db()
        self.assertEqual(self.preference.preferred_location, "Baneshwor")
        self.assertEqual(self.preference.preferred_room_type, "single_room")
        response = self.client.get(url)
        self.assertFalse(response.context["show_recommendations"])
        self.assertEqual(response.context["recommended_rooms"], [])
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertRedirects(self.client.get(url, {"initial": "preferences"}),
            url + "?q=Baneshwor&resolve=1&radius=2&max_budget=10000.00&room_type=single_room&furnishing=&setup_location=1", fetch_redirect_response=False)

    def test_find_rooms_map_boundary_top_six_and_invalid_input(self):
        rooms = [self.room() for _ in range(7)]
        far = self.room()
        ListingRevision.objects.filter(pk=far.published_revision_id).update(latitude="28.200000")
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:find_rooms")
        response = self.client.get(url, {"latitude": "27.7", "longitude": "85.3", "radius": "1", "point_source": "map"})
        self.assertEqual(len(response.context["recommended_rooms"]), 6)
        self.assertEqual(response.context["page_obj"].paginator.count, 8)
        self.assertNotIn(far.pk, [room.pk for room in response.context["recommended_rooms"]])
        self.assertEqual(response.context["recommended_rooms"][0].recommendation["percentage"], 100)
        response = self.client.get(url, self.selection(page="2"))
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(len(response.context["recommended_rooms"]), 6)
        self.assertIn("q=Baneshwor", response.context["pagination_query"])
        response = self.client.get(url, {"max_budget": "invalid"})
        self.assertFalse(response.context["show_recommendations"])
        self.assertEqual(response.context["page_obj"].paginator.count, 8)

    def test_text_lookup_applies_boundary_and_survives_pagination(self):
        near = self.room()
        far = self.room()
        ListingRevision.objects.filter(pk=far.published_revision_id).update(latitude="28.200000")
        self.lookup.return_value = ({"results": [{"latitude": 27.7, "longitude": 85.3, "label": "Baneshwor, Kathmandu"}]}, 200)
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:find_rooms")
        response = self.client.get(url, {"q": "Baneshwor", "resolve": "1", "radius": "2", "max_budget": "10000"})
        self.assertEqual(response.context["form"].cleaned_data["latitude"], 27.7)
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertEqual([room.pk for room in response.context["recommended_rooms"]], [near.pk])
        self.assertContains(response, "Active radius: 2 km")
        self.lookup.reset_mock()
        response = self.client.get(url + "?" + response.context["pagination_query"] + "&page=1")
        self.lookup.assert_not_called()
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.preference.refresh_from_db()
        self.assertIsNone(self.preference.latitude)
        self.assertEqual(self.preference.preferred_location, "Baneshwor")

    def test_location_choices_failures_and_stale_points(self):
        self.room()
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:find_rooms")
        first = {"latitude": 27.7, "longitude": 85.3, "label": "Nayabazar, Kathmandu"}
        other = {"latitude": 28.2, "longitude": 83.9, "label": "Nayabazar, Pokhara"}
        self.lookup.return_value = ({"results": [first, other]}, 200)
        response = self.client.get(url, {"q": "Nayabazar", "resolve": "1", "radius": "5", "room_type": "single_room",
            "latitude": "1", "longitude": "1", "point_location": "Old area"})
        self.assertIsNone(response.context["form"].cleaned_data["latitude"])
        self.assertEqual(len(response.context["location_choices"]), 2)
        self.assertContains(response, "No radius search runs until a location is selected")
        choice = response.context["location_choices"][0]
        self.lookup.reset_mock()
        response = self.client.get(url + "?" + choice["query"])
        self.lookup.assert_not_called()
        self.assertEqual(response.context["form"].cleaned_data["latitude"], 27.7)
        self.assertEqual(response.context["form"].cleaned_data["radius"], 5)
        self.assertEqual(response.context["form"].cleaned_data["room_type"], "single_room")
        self.lookup.return_value = ({"error": "Lookup temporarily unavailable."}, 503)
        response = self.client.get(url, {"q": "Sanepa", "resolve": "1", "latitude": "27.7", "longitude": "85.3", "point_location": "Baneshwor"})
        self.assertIsNone(response.context["form"].cleaned_data["latitude"])
        self.assertContains(response, "Nearby search is unavailable")

    def test_details_matches_card_context_and_ignores_supplied_percentage(self):
        listing = self.room(rent="20000", room_type="double_room")
        home_match = recommend_rooms(self.tenant, self.preference)[0].recommendation
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:room_details", args=[listing.pk])
        response = self.client.get(url, {"match_context": home_match["context"], "percentage": "100"})
        self.assertEqual(response.context["preference_match"]["result"]["percentage"], home_match["percentage"])
        self.assertContains(response, "Based on saved preferences")
        self.assertNotIn("percentage", response.context["search_query"])
        self.assertIn("location_token=", response.context["search_query"])
        self.assertEqual(len(response.context["preference_match"]["result"]["breakdown"]), 5)
        from accounts.room_search import RoomSearchForm
        form = RoomSearchForm(self.selection("Sanepa", max_budget="20000", room_type="double_room"))
        self.assertTrue(form.is_valid())
        search_match = recommend_rooms(self.tenant, filters=form.cleaned_data)[0].recommendation
        response = self.client.get(url, {"match_context": search_match["context"]})
        self.assertEqual(response.context["preference_match"]["result"]["score"], search_match["score"])
        self.assertContains(response, "Based on your search preferences")
        # The signed inputs preserve the original card score if Profile changes.
        TenantPreference.objects.filter(pk=self.preference.pk).update(maximum_budget=30000)
        response = self.client.get(url, {"match_context": home_match["context"]})
        self.assertEqual(response.context["preference_match"]["result"]["score"], home_match["score"])
        direct = self.client.get(url)
        self.assertNotEqual(direct.context["preference_match"]["result"]["score"], home_match["score"])
        response = self.client.get(url, self.selection("Sanepa", max_budget="20000", room_type="double_room"))
        self.assertEqual(response.context["preference_match"]["result"]["score"], search_match["score"])
        self.assertIn("location_token=", response.context["search_query"])
        self.assertIn("q=Sanepa", response.context["search_query"])

    def test_details_incomplete_invalid_and_foreign_context(self):
        listing = self.room()
        context = recommend_rooms(self.tenant, self.preference)[0].recommendation["context"]
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        url = reverse("accounts:room_details", args=[listing.pk])
        for parameters in ({"match_context": context + "bad"}, {"max_budget": "invalid"}):
            response = self.client.get(url, parameters)
            self.assertEqual(response.context["preference_match"], {})
            self.assertNotIn("result", response.context["preference_match"])
        TenantPreference.objects.filter(pk=self.preference.pk).delete()
        response = self.client.get(url)
        self.assertNotContains(response, 'id="preference-match-title"')
        self.assertEqual(response.context["preference_match"], {})
        other = User.objects.create_user(username="other-match", email="other-match@example.test")
        self.client.force_login(other, backend="accounts.backends.EmailBackend")
        response = self.client.get(url, {"match_context": context})
        self.assertEqual(response.context["preference_match"], {})
        RoomListing.objects.filter(pk=listing.pk).update(listing_status="inactive")
        self.assertEqual(self.client.get(url, {"match_context": context}).status_code, 404)

    def test_details_boundary_hides_component_without_blocking_room_access(self):
        near = self.room()
        far = self.room()
        ListingRevision.objects.filter(pk=far.published_revision_id).update(latitude="28.200000")
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        context = recommend_rooms(self.tenant, self.preference)[0].recommendation["context"]
        self.assertEqual(len(recommend_rooms(self.tenant, self.preference)), 1)
        near_url = reverse("accounts:room_details", args=[near.pk])
        far_url = reverse("accounts:room_details", args=[far.pk])
        self.assertContains(self.client.get(near_url, {"match_context": context}), 'id="preference-match-title"')
        for parameters in ({"match_context": context}, self.selection(), {}):
            response = self.client.get(far_url, parameters)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["can_request_room"])
            self.assertEqual(response.context["preference_match"], {})
            self.assertNotContains(response, 'id="preference-match-title"')
            self.assertNotContains(response, "Match unavailable")
        self.boundary_lookup.return_value = ({"results": []}, 200)
        response = self.client.get(near_url)
        self.assertEqual(response.context["preference_match"], {})
        self.assertNotContains(response, 'id="preference-match-title"')
        self.assertTrue(response.context["can_request_room"])
        self.assertEqual(recommend_rooms(self.tenant, self.preference), [])
        self.assertEqual(recommend_rooms(self.tenant, filters={"room_type": "single_room"}), [])

    def test_inclusive_sql_boundary_uses_the_same_distance_as_scoring(self):
        from listings.distance import room_distance_expression, rooms_within_radius, within_radius
        from listings.services import published_listings
        listing = self.room()
        point = (27.69, 85.3)
        distance = published_listings().filter(pk=listing.pk).annotate(
            measured=room_distance_expression(*point)).values_list("measured", flat=True).get()
        self.assertGreater(distance, 1)
        for radius, included in ((distance - 0.00000001, False), (distance, True), (distance + 0.00000001, True)):
            with self.subTest(radius=radius):
                self.assertEqual(rooms_within_radius(published_listings(), *point, radius).filter(pk=listing.pk).exists(), included)
                self.assertEqual(within_radius(distance, radius), included)
                result = score_room(self.preference, listing.published_revision, set(), set(), distance_km=distance, radius=radius)
                self.assertEqual(result is not None, included)
                if result:
                    self.assertEqual(result["factors"]["location"], 1)

    def test_geographic_location_restores_30_points_on_cards_and_details(self):
        from accounts.room_search import RoomSearchForm
        listing = self.room(rent="20000")
        form = RoomSearchForm(self.selection("Sanepa", max_budget="10000", room_type="single_room", furnishing="furnished"))
        self.assertTrue(form.is_valid())
        match = recommend_rooms(self.tenant, filters=form.cleaned_data)[0].recommendation
        self.assertEqual(match["percentage"], 85)
        self.assertEqual(match["factors"]["location"], 1)
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        response = self.client.get(reverse("accounts:room_details", args=[listing.pk]), {"match_context": match["context"]})
        detail = response.context["preference_match"]["result"]
        self.assertEqual(detail["percentage"], 85)
        self.assertEqual(detail["distance_km"], match["distance_km"])
        self.assertContains(response, "Within your selected area")
        self.assertNotContains(response, "Different location")
        response = self.client.get(reverse("accounts:find_rooms"), self.selection("Sanepa", max_budget="10000", room_type="single_room", furnishing="furnished"))
        self.assertEqual(response.context["recommended_rooms"][0].recommendation["percentage"], 85)
        self.assertContains(response, 'id="available-room-row"')
