from django.test import Client, TestCase
from django.urls import reverse

from .models import User


class LoginViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "  River!Cloud82  "
        cls.user = User.objects.create_user(
            username="internal", email="person@example.com", password=cls.password,
        )
        cls.inactive = User.objects.create_user(
            username="inactive", email="inactive@example.com", password=cls.password,
            is_active=False,
        )

    def setUp(self):
        self.url = reverse("accounts:login")

    def test_get_displays_empty_login_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertFalse(response.context["form"].is_bound)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, reverse("accounts:register"))
        self.assertContains(response, "Welcome Back!")
        self.assertContains(response, "/static/accounts/login.css")
        self.assertNotContains(response, "Forgot Password")

    def test_successful_login_creates_session_and_ignores_next(self):
        response = self.client.post(self.url + "?next=https://example.com/", {
            "email": "  PERSON@EXAMPLE.COM  ", "password": self.password,
            "next": "https://example.com/",
        })
        self.assertRedirects(response, reverse("accounts:tenant"))
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
        self.assertEqual(self.client.session["_auth_user_backend"], "accounts.backends.EmailBackend")

    def test_invalid_credentials_preserve_email_and_clear_password(self):
        for email in (self.user.email, "unknown@example.com", self.inactive.email):
            with self.subTest(email=email):
                password = self.password if email == self.inactive.email else "Wrong!Password82"
                response = self.client.post(self.url, {"email": email, "password": password})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Invalid email or password.")
                self.assertContains(response, f'value="{email}"')
                self.assertNotContains(response, password)
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_authenticated_get_and_post_redirect_tenant(self):
        self.client.force_login(self.user, backend="accounts.backends.EmailBackend")
        self.assertRedirects(self.client.get(self.url), reverse("accounts:tenant"))
        self.assertRedirects(self.client.post(self.url, {}), reverse("accounts:tenant"))

    def test_csrf_protection(self):
        response = Client(enforce_csrf_checks=True).post(self.url, {
            "email": self.user.email, "password": self.password,
        })
        self.assertEqual(response.status_code, 403)
