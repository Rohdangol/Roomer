from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.shortcuts import render
from django.test import RequestFactory, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from accounts.models import OwnerVerification
from core.context_processors import public_navigation


class SharedLayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = get_user_model().objects.create_user(username="tenant", email="tenant@example.com")
        cls.owner = get_user_model().objects.create_user(username="owner", email="owner@example.com", role="owner")
        cls.staff = get_user_model().objects.create_user(username="staff", email="staff@example.com", is_staff=True)

    def test_public_pages_share_layout_and_assets(self):
        for name in ("home", "accounts:login", "accounts:register"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertTemplateUsed(response, "core/base.html")
                if name == "home":
                    self.assertContains(response, 'aria-label="Main navigation"')
                    self.assertContains(response, 'aria-controls="site-navigation"')
                    self.assertTemplateUsed(response, "core/_footer.html")
                else:
                    self.assertTemplateUsed(response, "accounts/base_auth.html")
                    self.assertNotContains(response, 'class="site-header"')
                    self.assertContains(response, "Roomer logo placeholder")
                self.assertContains(response, "Skip to content")
                self.assertContains(response, "/static/core/layout.css")
                self.assertContains(response, "/static/core/layout.js")
                self.assertContains(response, "Sign up" if name == "accounts:login" else "Create Account")

    def test_role_pages_use_top_navigation_and_mark_current_page(self):
        OwnerVerification.objects.create(user=self.owner, document_type="citizenship", document="test.pdf", status="approved", submitted_at=timezone.now())
        for user, route in ((self.tenant, "accounts:tenant"), (self.owner, "accounts:owner")):
            self.client.force_login(user, backend="accounts.backends.EmailBackend")
            response = self.client.get(reverse(route))
            self.assertTemplateUsed(response, "accounts/base_role.html")
            self.assertNotContains(response, "sidebar-navigation")
            self.assertContains(response, 'aria-label="Main navigation"')
            self.assertTemplateUsed(response, "core/_footer.html")
            self.assertContains(response, f'href="{reverse(route)}" aria-current="page"')
            self.assertContains(response, "csrfmiddlewaretoken")

    def test_custom_admin_shell_links_only_to_implemented_admin_routes(self):
        request = RequestFactory().get(reverse("accounts:admin"))
        request.user = self.staff
        request.resolver_match = resolve(request.path)
        with self.assertTemplateUsed("core/_navigation_admin.html"), self.assertTemplateUsed("core/_footer_admin.html"):
            response = render(request, "custom_admin/base.html")
        self.assertContains(response, reverse("accounts:admin"))
        self.assertNotContains(response, reverse("admin:accounts_ownerverification_changelist"))

    def test_wireframe_labels_profile_identity_and_disabled_destinations(self):
        import re

        self.tenant.full_name = "Actual Tenant"
        self.tenant.save()
        for user, route, labels in (
            (self.tenant, "accounts:tenant", ["Home", "Find Rooms", "Saved", "My Requests", "Agreements"]),
            (self.owner, "accounts:verification", ["Home", "My Listings", "Requests", "Agreements"]),
            (self.staff, "home", ["Home", "Users", "Listings", "Agreements"]),
        ):
            self.client.force_login(user, backend="accounts.backends.EmailBackend")
            response = self.client.get(reverse(route))
            html = response.content.decode()
            nav = html.split('id="site-navigation"', 1)[1].split("</nav>", 1)[0]
            text = re.sub(r"<[^>]*>", " ", nav)
            positions = [text.index(label) for label in labels]
            self.assertEqual(positions, sorted(positions))
            self.assertContains(response, 'aria-disabled="true"')
            self.assertNotContains(response, 'href="#"')
            self.assertContains(response, user.full_name or user.email)
            profile = html.split('class="profile-control header-dropdown"', 1)[1].split("</details>", 1)[0]
            self.assertIn('method="post"', profile)
            self.assertIn("csrfmiddlewaretoken", profile)
            self.assertIn("Logout", profile)

    def test_navigation_matches_user_access(self):
        for user, destination, other in (
            (self.tenant, "accounts:tenant", "accounts:owner"),
            (self.staff, "accounts:admin", "accounts:tenant"),
        ):
            with self.subTest(user=user.username):
                self.client.force_login(user, backend="accounts.backends.EmailBackend")
                response = self.client.get(reverse("home"))
                self.assertContains(response, reverse(destination))
                self.assertNotContains(response, reverse(other))
                self.assertContains(response, "Notifications")
                self.assertContains(response, "No new notifications.")
                self.assertContains(response, "csrfmiddlewaretoken")
                self.assertNotContains(response, "Create Account")

    def test_owner_notifications_follow_verification_status(self):
        self.client.force_login(self.owner, backend="accounts.backends.EmailBackend")
        response = self.client.get(reverse("accounts:verification"))
        self.assertTemplateUsed(response, "core/base.html")
        self.assertContains(response, "Submit your identity document to access Roomer.")
        self.assertNotContains(response, reverse("accounts:owner"))
        submission = OwnerVerification.objects.create(user=self.owner, document_type="citizenship", document="test.pdf", submitted_at=timezone.now())
        for status, notice in (
            ("pending", "Your verification is awaiting admin review."),
            ("rejected", "Your verification was rejected."),
            ("approved", "Your identity verification is approved."),
        ):
            submission.status = status
            submission.save()
            response = self.client.get(reverse("accounts:verification"))
            self.assertContains(response, notice)
        self.assertContains(response, reverse("accounts:owner"))

    def test_messages_render_once_with_severity_and_escaping(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        messages.success(request, "Completed successfully.")
        messages.error(request, "<script>unsafe</script>")
        response = render(request, "core/home.html")
        self.assertContains(response, "Completed successfully.", count=1)
        self.assertContains(response, 'role="alert"')
        self.assertContains(response, "&lt;script&gt;unsafe&lt;/script&gt;")
        self.assertNotContains(response, "<script>unsafe</script>")

    def test_context_processor_uses_existing_destinations(self):
        request = RequestFactory().get("/")
        request.user = self.owner
        self.assertEqual(public_navigation(request)["navigation_destination"], "accounts:verification")
