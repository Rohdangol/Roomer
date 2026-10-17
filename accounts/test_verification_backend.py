from datetime import date
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import unquote
import time

from django.core import mail, signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import FileSystemStorage
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils.functional import SimpleLazyObject

from listings.tests import image_upload
from .models import TenantIdentityAttempt, TenantIdentityReview, User
from .verification_services import confirm_email, email_is_verified, review_tenant_identity, send_verification_email, submit_tenant_identity


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class VerificationBackendTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(username="tenant", email="tenant@example.com")
        self.other = User.objects.create_user(username="other", email="other@example.com")
        self.admin = User.objects.create_superuser(username="admin", email="admin@example.com")
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name in ("front_document", "back_document"):
            storage = patch.object(TenantIdentityAttempt._meta.get_field(name), "storage", FileSystemStorage(location=directory.name))
            storage.start()
            self.addCleanup(storage.stop)

    def email_token(self):
        with self.captureOnCommitCallbacks(execute=True):
            send_verification_email(SimpleLazyObject(lambda:self.tenant), RequestFactory().get("/"))
        return unquote(mail.outbox[-1].body.splitlines()[-1].rstrip("/").split("/")[-1])

    def test_signed_email_expiry_throttling_and_persisted_proof(self):
        token = self.email_token()
        self.assertEqual(send_verification_email(self.tenant, RequestFactory().get("/")), "limited")
        with self.assertRaises(signing.BadSignature):
            confirm_email(token + "invalid")
        future = time.time() + 86401
        with patch("django.core.signing.time.time", return_value=future), self.assertRaises(signing.SignatureExpired):
            confirm_email(token)
        self.tenant.refresh_from_db()
        self.assertFalse(email_is_verified(self.tenant))
        confirm_email(token)
        self.tenant.refresh_from_db()
        self.assertTrue(email_is_verified(self.tenant))
        self.assertEqual(send_verification_email(self.tenant, RequestFactory().get("/")), "verified")
        self.tenant.email = "changed@example.com"
        self.tenant.save()
        self.assertFalse(email_is_verified(self.tenant))

    def submit(self):
        return submit_tenant_identity(SimpleLazyObject(lambda:self.tenant), {"document_type":"citizenship", "document_number":"123", "issued_date":date(2020,1,1), "front_document":image_upload(), "back_document":image_upload()})

    def test_identity_authorization_and_immutable_review_history(self):
        attempt = self.submit()
        with self.assertRaises(ValidationError): self.submit()
        with self.assertRaises(PermissionDenied): review_tenant_identity(self.other, attempt.pk, "approved")
        self.assertEqual(review_tenant_identity(self.admin, attempt.pk, "rejected", "Unreadable"), "applied")
        second = self.submit()
        attempt.refresh_from_db()
        self.assertEqual(attempt.rejection_reason,"Unreadable")
        self.assertNotEqual(attempt.pk, second.pk)
        self.assertEqual(review_tenant_identity(self.admin, attempt.pk, "approved"), "stale")
        self.assertEqual(review_tenant_identity(self.admin, second.pk, "approved"), "applied")
        with self.assertRaises(ValidationError): self.submit()
        self.assertEqual(TenantIdentityReview.objects.count(),3)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("accounts:tenant_identity_document",args=[attempt.pk,"front"])).status_code,404)
        self.client.force_login(self.tenant)
        response=self.client.get(reverse("accounts:tenant_identity_document",args=[attempt.pk,"front"]))
        self.assertEqual(response.status_code,200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))

    def test_id_rejects_permission_fields_bad_images_and_future_dates(self):
        details={"document_type":"national_id", "document_number":"123", "issued_date":date(2099,1,1), "front_document":image_upload(), "back_document":image_upload()}
        with self.assertRaises(ValidationError): submit_tenant_identity(self.tenant,details)
        details.update(issued_date=date(2020,1,1), status="approved")
        with self.assertRaises(ValidationError): submit_tenant_identity(self.tenant,details)
        details.pop("status")
        from django.core.files.uploadedfile import SimpleUploadedFile
        details["front_document"]=SimpleUploadedFile("fake.png", b"invalid")
        with self.assertRaises(ValidationError): submit_tenant_identity(self.tenant,details)

    def test_profile_upload_and_email_confirmation_require_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.tenant)
        response = client.get(reverse("accounts:tenant_profile"))
        self.assertContains(response, "0 of 2 steps completed")
        data={"action":"identity", "document_type":"citizenship", "document_number":"123", "issued_date":"2020-01-01", "front_document":image_upload(), "back_document":image_upload(), "status":"approved"}
        self.assertEqual(client.post(reverse("accounts:tenant_profile"), data).status_code,403)
        data.update(front_document=image_upload(), back_document=image_upload(), csrfmiddlewaretoken=client.cookies["csrftoken"].value)
        self.assertEqual(client.post(reverse("accounts:tenant_profile"),data).status_code,302)
        self.assertEqual(TenantIdentityAttempt.objects.get(user=self.tenant).status,"pending")
        token=self.email_token()
        url=reverse("accounts:verify_email",args=[token])
        self.assertEqual(client.post(url).status_code,403)
        client.get(url)
        self.assertEqual(client.post(url,{"csrfmiddlewaretoken":client.cookies["csrftoken"].value}).status_code,302)
        self.tenant.refresh_from_db()
        self.assertTrue(email_is_verified(self.tenant))
