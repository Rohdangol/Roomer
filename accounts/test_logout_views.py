from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse

from .models import User


class LogoutViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="internal", email="person@example.com")

    def setUp(self):
        self.url = reverse("accounts:logout")
        self.client.force_login(self.user, backend="accounts.backends.EmailBackend")

    def test_post_removes_session_and_redirects_with_message(self):
        old_session_key = self.client.session.session_key
        session = self.client.session
        session["temporary"] = "value"
        session.save()
        response = self.client.post(self.url, follow=True)
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertContains(response, "You have been signed out.")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("temporary", self.client.session)
        self.assertFalse(Session.objects.filter(session_key=old_session_key).exists())

    def test_get_returns_405_and_preserves_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers["Allow"], "POST")
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_csrf_failure_preserves_login(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user, backend="accounts.backends.EmailBackend")
        response = client.post(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.session["_auth_user_id"], str(self.user.pk))

    def test_csrf_protected_home_form_can_log_out(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user, backend="accounts.backends.EmailBackend")
        client.get(reverse("home"))
        response = client.post(self.url, {"csrfmiddlewaretoken": client.cookies["csrftoken"].value})
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", client.session)

    def test_anonymous_post_redirects_with_message(self):
        client = Client()
        response = client.post(self.url, follow=True)
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertContains(response, "You have been signed out.")
        self.assertNotIn("_auth_user_id", client.session)
