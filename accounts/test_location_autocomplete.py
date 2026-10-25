"""Focused selection, CSRF, radius and onboarding checks; no live provider calls."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from accounts.search_location import signed_place
from preferences.models import TenantPreference


class AutocompleteChecks(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(username="autocomplete-tenant", email="autocomplete@example.test")
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        self.place = signed_place({"label": "Nayabazar, Kathmandu", "latitude": 27.72, "longitude": 85.31})

    def test_suggestions_permissions_csrf_and_signed_selection(self):
        url = reverse("accounts:tenant_location_suggestions")
        with patch("accounts.listing_geocoding.lookup_text_location", return_value=({"results": [
                {"label": "Nayabazar, Kathmandu", "latitude": 27.72, "longitude": 85.31}]}, 200)) as lookup:
            response = self.client.post(url, {"q": "Nayabazar"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["results"][0]["location_token"])
            lookup.assert_called_once_with("Nayabazar")
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        self.assertEqual(strict.post(url, {"q": "Nayabazar"}).status_code, 403)
        self.client.logout()
        owner = User.objects.create_user(username="autocomplete-owner", email="autocomplete-owner@example.test", role="owner")
        self.client.force_login(owner, backend="accounts.backends.EmailBackend")
        self.assertEqual(self.client.post(url, {"q": "Nayabazar"}).status_code, 403)

    def test_text_only_forged_stale_and_invalid_coordinates_cannot_search(self):
        url = reverse("accounts:find_rooms")
        for parameters in ({"q": "Nayabazar"}, {**self.place, "latitude": "27.73"},
                {**self.place, "q": "Sanepa"}, {**self.place, "latitude": "91"}):
            with self.subTest(parameters=parameters):
                response = self.client.get(url, parameters)
                self.assertEqual(response.context["page_obj"].paginator.count, 0)
                self.assertFalse(response.context["show_recommendations"])
                self.assertTrue(response.context["form"].errors)
        response = self.client.get(url, self.place)
        self.assertFalse(response.context["form"].errors)
        self.assertEqual(response.context["form"].cleaned_data["radius"], 2)

    def test_home_requires_selection_but_reset_and_fresh_stay_unfiltered(self):
        home = reverse("accounts:tenant")
        for value in ("", "Nayabazar"):
            response = self.client.get(home, {"q": value, "search": "1"})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Choose a location from the suggestions.")
            self.assertFalse(response.context["show_preferences"])
        for parameters in ({}, {"entry": "fresh"}):
            response = self.client.get(reverse("accounts:find_rooms"), parameters)
            self.assertFalse(response.context["form"].errors)
            self.assertFalse(response.context["show_recommendations"])

    def test_selection_survives_onboarding_without_saving_search_coordinates(self):
        home = reverse("accounts:tenant")
        response = self.client.get(home, {**self.place, "search": "1"})
        self.assertTrue(response.context["show_preferences"])
        self.assertContains(response, self.place["location_token"])
        data = {**self.place, "preferred_location": self.place["q"], "maximum_budget": "15000",
                "preferred_room_type": "single_room", "preferred_furnishing": "any"}
        invalid = self.client.post(home, {**data, "maximum_budget": "-1"})
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, self.place["location_token"])
        response = self.client.post(home, data)
        self.assertEqual(response.status_code, 302)
        parameters = parse_qs(urlsplit(response.url).query)
        self.assertEqual(parameters["latitude"], [self.place["latitude"]])
        preference = TenantPreference.objects.get(tenant=self.tenant)
        self.assertIsNone(preference.latitude)
        original = preference.preferred_location
        new_place = signed_place({"label": "Sanepa, Lalitpur", "latitude": 27.68, "longitude": 85.30})
        response = self.client.get(home, {**new_place, "search": "1"})
        self.assertEqual(response.status_code, 302)
        preference.refresh_from_db()
        self.assertEqual(preference.preferred_location, original)
        self.assertEqual(parse_qs(urlsplit(response.url).query)["q"], ["Sanepa, Lalitpur"])
