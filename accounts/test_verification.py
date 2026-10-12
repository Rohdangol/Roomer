from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import OwnerVerification, User
from .storage import PrivateDocumentStorage


class OwnerVerificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(username="owner", email="owner@example.com", role="owner", password="River!Cloud82")
        cls.other = User.objects.create_user(username="other", email="other@example.com", role="owner")
        cls.tenant = User.objects.create_user(username="tenant", email="tenant@example.com")
        cls.admin = User.objects.create_superuser(username="reviewer", email="admin@example.com", password="River!Cloud82")

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        storage_patch = patch.object(OwnerVerification._meta.get_field("document"), "storage", FileSystemStorage(location=self.directory.name))
        storage_patch.start()
        self.addCleanup(storage_patch.stop)
        self.url = reverse("accounts:verification")
        self.client.force_login(self.owner, backend="accounts.backends.EmailBackend")

    def upload(self, document_type="citizenship", content=b"%PDF-1.4\nTest document", name="identity.pdf", **extra):
        return self.client.post(self.url, {
            "document_type": document_type,
            "document": SimpleUploadedFile(name, content, content_type="application/pdf"),
            **extra,
        })

    def submit(self):
        response = self.upload()
        self.assertRedirects(response, self.url)
        return OwnerVerification.objects.get(user=self.owner)

    def admin_review(self, submission, status, reason="", version=None):
        self.client.force_login(self.admin, backend="django.contrib.auth.backends.ModelBackend")
        return self.client.post(reverse("admin:accounts_ownerverification_change", args=[submission.pk]), {
            "status": status, "rejection_reason": reason,
            "submitted_version": version or submission.submitted_at.isoformat(), "_save": "Save",
        })

    def test_both_document_choices_create_pending_private_submission(self):
        for user, kind in ((self.owner, "citizenship"), (self.other, "national_id")):
            self.client.force_login(user, backend="accounts.backends.EmailBackend")
            self.assertRedirects(self.upload(kind, status="approved", reviewed_by=self.admin.pk), self.url)
            submission = OwnerVerification.objects.get(user=user)
            self.assertEqual(submission.document_type, kind)
            self.assertEqual(submission.status, "pending")
            self.assertIsNone(submission.reviewed_by)
            self.assertTrue(submission.document.storage.exists(submission.document.name))
            self.assertNotIn("identity.pdf", submission.document.name)
        with self.assertRaises(ValueError):
            PrivateDocumentStorage().url("identity.pdf")

    def test_invalid_or_missing_uploads(self):
        for kind, content, name in (
            ("passport", b"%PDF-1.4", "identity.pdf"),
            ("citizenship", b"html", "identity.pdf"),
            ("citizenship", b"%PDF-1.4", "identity.html"),
            ("citizenship", b"%PDF-" + b"x" * (5 * 1024 * 1024), "identity.pdf"),
        ):
            with self.subTest(kind=kind, name=name):
                response = self.upload(kind, content, name)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(self.client.post(self.url, {}).status_code, 200)
        self.assertEqual(OwnerVerification.objects.count(), 0)

    def test_pending_submission_cannot_be_overwritten(self):
        submission = self.submit()
        name, submitted = submission.document.name, submission.submitted_at
        self.assertRedirects(self.upload("national_id"), self.url)
        submission.refresh_from_db()
        self.assertEqual(submission.document.name, name)
        self.assertEqual(submission.submitted_at, submitted)

    def test_owner_login_and_direct_home_are_restricted(self):
        self.assertRedirects(self.client.get(reverse("home")), self.url)
        self.assertRedirects(self.client.get(reverse("accounts:login")), self.url)
        self.client.logout()
        response = self.client.post(reverse("accounts:login"), {"email": self.owner.email, "password": "River!Cloud82"})
        self.assertRedirects(response, self.url)
        self.assertIn("_auth_user_id", self.client.session)
        self.submit()
        self.assertRedirects(self.client.get(reverse("home")), self.url)

    def test_approval_unlocks_existing_owner_session(self):
        submission = self.submit()
        response = self.admin_review(submission, "approved")
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, "approved")
        self.assertEqual(submission.reviewed_by, self.admin)
        self.assertIsNotNone(submission.reviewed_at)
        self.client.force_login(self.owner, backend="accounts.backends.EmailBackend")
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertContains(self.client.get(self.url), "Your identity has been approved.")
        self.assertRedirects(self.upload(), self.url)
        submission.refresh_from_db()
        self.assertEqual(submission.status, "approved")

    def test_rejection_requires_reason_and_allows_resubmission(self):
        submission = self.submit()
        response = self.admin_review(submission, "rejected")
        self.assertContains(response, "Explain why the document was rejected.")
        submission.refresh_from_db()
        self.assertEqual(submission.status, "pending")
        self.assertEqual(self.admin_review(submission, "rejected", "Document is unreadable.").status_code, 302)
        self.client.force_login(self.owner, backend="accounts.backends.EmailBackend")
        self.assertContains(self.client.get(self.url), "Document is unreadable.")
        self.assertRedirects(self.client.get(reverse("home")), self.url)
        self.assertRedirects(self.upload("national_id"), self.url)
        submission.refresh_from_db()
        self.assertEqual(submission.status, "pending")
        self.assertEqual(submission.rejection_reason, "")
        self.assertIsNone(submission.reviewed_by)
        self.assertIsNone(submission.reviewed_at)
        self.assertEqual(OwnerVerification.objects.filter(user=self.owner).count(), 1)

    def test_stale_admin_review_is_rejected(self):
        submission = self.submit()
        response = self.admin_review(submission, "approved", version=(timezone.now()).isoformat())
        self.assertContains(response, "This submission changed.")
        submission.refresh_from_db()
        self.assertEqual(submission.status, "pending")

    def test_document_download_requires_owner_or_authorized_reviewer(self):
        submission = self.submit()
        url = reverse("accounts:verification_document", args=[submission.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4\nTest document")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.client.force_login(self.other, backend="accounts.backends.EmailBackend")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.other.is_staff = True
        self.other.save()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.other.user_permissions.add(Permission.objects.get(codename="view_ownerverification"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        b"".join(response.streaming_content)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_tenants_and_anonymous_visitors_keep_home_access(self):
        self.client.force_login(self.tenant, backend="accounts.backends.EmailBackend")
        self.assertRedirects(self.client.get(self.url), reverse("home"))
        self.assertRedirects(self.upload(), reverse("home"))
        self.assertEqual(OwnerVerification.objects.count(), 0)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_submission_and_admin_review_require_csrf_and_permissions(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner, backend="accounts.backends.EmailBackend")
        self.assertEqual(client.post(self.url, {}).status_code, 403)
        submission = self.submit()
        self.owner.is_staff = True
        self.owner.save()
        self.assertEqual(self.client.get(reverse("admin:accounts_ownerverification_change", args=[submission.pk])).status_code, 403)
