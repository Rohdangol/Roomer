from unittest.mock import patch

from django.contrib.auth import authenticate
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .backends import EmailBackend
from .forms import EmailLoginForm
from .models import User


class EmailAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "  Strong!Password82  "
        cls.tenant = User.objects.create_user(
            username="tenant-internal", email="tenant@example.com", password=cls.password,
        )
        cls.owner = User.objects.create_user(
            username="owner-internal", email="owner@example.com", password=cls.password,
            role=User.Role.OWNER,
        )
        cls.inactive = User.objects.create_user(
            username="inactive", email="inactive@example.com", password=cls.password,
            is_active=False,
        )
        cls.admin = User.objects.create_superuser(
            username="roomer-admin", email="admin@example.com", password=cls.password,
        )

    def test_tenant_and_owner_authenticate_with_normalized_email(self):
        for user in (self.tenant, self.owner):
            with self.subTest(role=user.role):
                result = authenticate(email=f"  {user.email.upper()}  ", password=self.password)
                self.assertEqual(result, user)
                self.assertEqual(result.backend, "accounts.backends.EmailBackend")

    def test_bad_credentials_and_inactive_users_are_rejected(self):
        for email, password in (
            (self.tenant.email, "wrong-password"),
            ("missing@example.com", self.password),
            (self.inactive.email, self.password),
            (self.tenant.email, self.password.strip()),
        ):
            with self.subTest(email=email):
                self.assertIsNone(authenticate(email=email, password=password))

    def test_unknown_email_performs_dummy_password_hash(self):
        original_set_password = User.set_password
        with patch.object(User, "set_password", autospec=True, side_effect=original_set_password) as hashing:
            self.assertIsNone(EmailBackend().authenticate(None, email="missing@example.com", password=self.password))
        hashing.assert_called_once()
        self.assertEqual(hashing.call_args.args[1], self.password)

    def test_email_backend_does_not_reinterpret_username(self):
        with patch.object(User.objects, "get") as lookup:
            result = EmailBackend().authenticate(None, username=self.tenant.email, password=self.password)
        self.assertIsNone(result)
        lookup.assert_not_called()
        self.assertIsNone(authenticate(username=self.tenant.email, password=self.password))

    def test_form_authenticates_and_preserves_password(self):
        request = RequestFactory().post("/")
        form = EmailLoginForm(request=request, data={
            "email": "  TENANT@EXAMPLE.COM  ", "password": self.password,
        })
        self.assertIsNone(form.get_user())
        with patch("accounts.forms.authenticate", wraps=authenticate) as authentication:
            self.assertTrue(form.is_valid(), form.errors)
        authentication.assert_called_once_with(request, email=self.tenant.email, password=self.password)
        self.assertEqual(form.get_user(), self.tenant)
        self.assertEqual(form.cleaned_data["password"], self.password)

    def test_form_uses_same_error_for_all_failed_credentials(self):
        for email, password in (
            ("unknown@example.com", self.password),
            (self.tenant.email, "wrong-password"),
            (self.inactive.email, self.password),
        ):
            with self.subTest(email=email):
                form = EmailLoginForm(data={"email": email, "password": password})
                self.assertFalse(form.is_valid())
                self.assertEqual(form.non_field_errors(), ["Invalid email or password."])
                self.assertIsNone(form.get_user())

    def test_form_requires_email_and_password(self):
        form = EmailLoginForm(data={})
        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), {"email", "password"})
        self.assertIsNone(form.get_user())

    def test_existing_admin_username_login_works(self):
        user = authenticate(username=self.admin.username, password=self.password)
        self.assertEqual(user, self.admin)
        self.assertEqual(user.backend, "django.contrib.auth.backends.ModelBackend")
        response = self.client.post(reverse("admin:login"), {
            "username": self.admin.username, "password": self.password,
            "next": reverse("admin:index"),
        })
        self.assertRedirects(response, reverse("admin:index"))
        self.assertEqual(self.client.session["_auth_user_id"], str(self.admin.pk))
