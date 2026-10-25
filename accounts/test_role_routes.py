from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import OwnerVerification, User


class RoleRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = "River!Cloud82"
        cls.tenant = User.objects.create_user(username="tenant", email="tenant@example.com", password=cls.password)
        cls.owner = User.objects.create_user(username="owner", email="owner@example.com", role="owner", password=cls.password)
        cls.staff = User.objects.create_user(username="staff", email="staff@example.com", is_staff=True, password=cls.password)
        cls.superuser = User.objects.create_superuser(username="admin", email="admin@example.com", password=cls.password)

    def sign_in(self, user):
        self.client.force_login(user, backend="accounts.backends.EmailBackend")

    def approve_owner(self):
        return OwnerVerification.objects.create(
            user=self.owner, document_type="citizenship", document="test.pdf",
            status="approved", submitted_at=timezone.now(),
        )

    def test_anonymous_role_routes_require_login(self):
        for name in ("tenant", "owner", "admin"):
            with self.subTest(name=name):
                url = reverse(f"accounts:{name}")
                self.assertRedirects(self.client.get(url), reverse("accounts:login") + "?next=" + url)

    def test_tenant_access_and_cross_role_denials(self):
        self.sign_in(self.tenant)
        self.assertContains(self.client.get(reverse("accounts:tenant")), "Find a place that")
        self.assertEqual(self.client.get(reverse("accounts:owner")).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:admin")).status_code, 403)

    def test_owner_verification_states_and_current_session(self):
        self.sign_in(self.owner)
        owner_url = reverse("accounts:owner")
        verification_url = reverse("accounts:verification")
        self.assertRedirects(self.client.get(owner_url), verification_url)
        submission = self.approve_owner()
        for status in ("pending", "rejected"):
            submission.status = status
            submission.save()
            self.assertRedirects(self.client.get(owner_url), verification_url)
        submission.status = "approved"
        submission.save()
        self.assertContains(self.client.get(owner_url), "Welcome Back Owner")
        self.assertEqual(self.client.get(reverse("accounts:tenant")).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:admin")).status_code, 403)

    def test_staff_and_superuser_access_admin_only(self):
        for user in (self.staff, self.superuser):
            with self.subTest(user=user.username):
                self.sign_in(user)
                self.assertEqual(self.client.get(reverse("accounts:admin")).status_code, 200)
                for name in ("tenant", "owner"):
                    self.assertEqual(self.client.get(reverse(f"accounts:{name}")).status_code, 403)

    def test_staff_destination_takes_priority_over_owner_role(self):
        self.staff.role = "owner"
        self.staff.save()
        self.sign_in(self.staff)
        self.assertRedirects(self.client.get(reverse("accounts:login")), reverse("accounts:admin"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("home")), reverse("accounts:admin"))

    def test_login_post_and_authenticated_get_use_role_destination(self):
        self.approve_owner()
        for user, name in ((self.tenant, "tenant"), (self.owner, "owner"), (self.staff, "admin"), (self.superuser, "admin")):
            with self.subTest(name=name, user=user.username):
                self.client.logout()
                destination = reverse(f"accounts:{name}")
                response = self.client.post(reverse("accounts:login") + "?next=https://example.com/", {
                    "email": user.email, "password": self.password,
                    "next": reverse("accounts:admin"), "role": "admin",
                })
                self.assertRedirects(response, destination, fetch_redirect_response=False)
                self.assertRedirects(self.client.get(reverse("accounts:login")), destination, fetch_redirect_response=False)

    def test_inactive_staff_cannot_authenticate_or_access_admin(self):
        self.staff.is_active = False
        self.staff.save()
        self.sign_in(self.staff)
        self.assertEqual(self.client.get(reverse("accounts:admin")).status_code, 302)
        response = self.client.post(reverse("accounts:login"), {"email": self.staff.email, "password": self.password})
        self.assertContains(response, "Invalid email or password.")

    def test_home_links_to_current_account_area(self):
        self.sign_in(self.tenant)
        self.assertContains(self.client.get(reverse("home")), reverse("accounts:tenant"))
