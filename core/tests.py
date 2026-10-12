from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class HomeSessionTests(TestCase):
    def test_anonymous_home_has_account_links(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, reverse("accounts:login"))
        self.assertContains(response, "Sign In")
        self.assertContains(response, reverse("accounts:register"))
        self.assertContains(response, "Create Account")
        self.assertNotContains(response, "Logout")

    def test_authenticated_home_shows_name_role_and_logout_form(self):
        user = get_user_model().objects.create_user(
            username="internal", email="person@example.com", full_name="Sample Person", role="owner",
        )
        self.client.force_login(user, backend="accounts.backends.EmailBackend")
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Welcome, Sample Person")
        self.assertContains(response, "Role: Owner")
        self.assertContains(response, f'action="{reverse("accounts:logout")}"')
        self.assertContains(response, 'method="post"')
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertNotContains(response, "Create Account")

    def test_blank_name_falls_back_to_email(self):
        user = get_user_model().objects.create_user(username="internal", email="person@example.com")
        self.client.force_login(user, backend="accounts.backends.EmailBackend")
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Welcome, person@example.com")
        self.assertContains(response, "Role: Tenant")
