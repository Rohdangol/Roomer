from datetime import timedelta
import hashlib
import logging
import secrets
from hmac import compare_digest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.urls import reverse

from .models import EmailVerificationDelivery, TenantIdentityAttempt, TenantIdentityReview
from .storage import validate_identity_document

SALT = "roomer.registration-email"
logger = logging.getLogger("django.server")


def email_is_verified(user):
    return bool(user.email_verified_at and user.verified_email == user.email)


@transaction.atomic
def send_verification_email(user, request):
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    if email_is_verified(user):
        logger.info("Verification resend skipped: email is already verified.")
        return "verified"
    now = timezone.now()
    delivery = EmailVerificationDelivery.objects.filter(user=user).first()
    if delivery and (now - delivery.sent_at < timedelta(seconds=60) or (now - delivery.window_started_at < timedelta(hours=1) and delivery.window_count >= 5)):
        logger.info("Verification resend skipped: rate limit active (60-second cooldown / 5 per hour).")
        return "limited"
    if delivery is None:
        delivery = EmailVerificationDelivery(user=user, window_started_at=now)
    if now - delivery.window_started_at >= timedelta(hours=1):
        delivery.window_started_at, delivery.window_count = now, 0
    nonce = secrets.token_urlsafe(32)
    delivery.nonce_digest = hashlib.sha256(nonce.encode()).hexdigest()
    delivery.sent_at = now
    delivery.window_count += 1
    delivery.save()
    token = signing.dumps({"user": user.pk, "email": user.email, "nonce": nonce}, salt=SALT)
    link = request.build_absolute_uri(reverse("accounts:verify_email", args=[token]))
    # Commit rate counters before delivery so failed SMTP requests cannot bypass throttling.
    def deliver():
        logger.info("Verification email delivery starting after commit; backend=%s", settings.EMAIL_BACKEND)
        try:
            sent = send_mail("Verify your Roomer email", f"Confirm your email within 24 hours:\n{link}", settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
            if sent != 1:
                raise RuntimeError("Email backend reported no message delivered.")
        except Exception as error:
            # Do not log tokens, recipient addresses, SMTP credentials or exception payloads.
            logger.error("Verification email delivery failed: %s", type(error).__name__)
            raise
        logger.info("Verification email delivery completed (one message).")
    transaction.on_commit(deliver)
    return "sent"


@transaction.atomic
def confirm_email(token):
    payload = signing.loads(token, salt=SALT, max_age=86400)
    user = get_user_model().objects.select_for_update().filter(pk=payload["user"]).first()
    if user is None:
        raise signing.BadSignature("Account unavailable.")
    if user.email != payload["email"]:
        raise signing.BadSignature("Email has changed.")
    if email_is_verified(user):
        return user
    delivery = EmailVerificationDelivery.objects.filter(user=user).first()
    digest = hashlib.sha256(payload["nonce"].encode()).hexdigest()
    if not delivery or not compare_digest(delivery.nonce_digest, digest):
        raise signing.BadSignature("Link has been replaced or used.")
    user.email_verified_at, user.verified_email = timezone.now(), user.email
    user.save(update_fields=["email_verified_at", "verified_email"])
    delivery.delete()
    return user


@transaction.atomic
def submit_tenant_identity(actor, details):
    if not actor.is_authenticated or not actor.is_active or actor.is_staff or actor.role != "tenant":
        raise PermissionDenied
    get_user_model().objects.select_for_update().get(pk=actor.pk)
    if TenantIdentityAttempt.objects.filter(user=actor, status__in=["pending", "approved"]).exists():
        raise ValidationError("A pending or approved document cannot be replaced.")
    if set(details) != {"document_type", "document_number", "issued_date", "front_document", "back_document"}:
        raise ValidationError("Provide document details only; review fields are server-controlled.")
    attempt = TenantIdentityAttempt(user=actor, **details)
    for document in (attempt.front_document, attempt.back_document):
        validate_tenant_document(document)
    attempt.full_clean()
    attempt.save()
    return attempt


def validate_tenant_document(document):
    # Tenant uploads use decoded images, not signature-only checks. PDF remains owner-only.
    from listings.storage import validate_photo
    if not document.name.lower().endswith((".jpg", ".jpeg", ".png")):
        raise ValidationError("Upload a JPEG or PNG image, up to 5 MB.")
    validate_photo(document)


@transaction.atomic
def review_tenant_identity(actor, attempt_id, decision, reason=""):
    if not actor.is_active or not actor.is_staff or not actor.has_perm("accounts.change_tenantidentityattempt"):
        raise PermissionDenied
    attempt = TenantIdentityAttempt.objects.select_for_update().get(pk=attempt_id)
    reason = reason.strip()
    outcome = "applied"
    if attempt.status != "pending":
        outcome = "stale"
    elif decision not in ("approved", "rejected") or (decision == "rejected" and not reason):
        outcome = "invalid"
    TenantIdentityReview.objects.create(attempt=attempt, reviewer=actor, decision=decision, rejection_reason=reason, outcome=outcome)
    if outcome == "applied":
        TenantIdentityAttempt.objects.filter(pk=attempt.pk).update(status=decision, reviewed_by=actor, reviewed_at=timezone.now(), rejection_reason=reason if decision == "rejected" else "")
    return outcome


@transaction.atomic
def review_owner_identity(actor, submission_id, decision, reason, submitted_version):
    from .models import OwnerVerification
    if not actor.is_authenticated or not actor.is_active or not actor.is_staff or not actor.has_perm("accounts.change_ownerverification"):
        raise PermissionDenied
    submission = OwnerVerification.objects.select_for_update().get(pk=submission_id)
    if submission.user_id == actor.pk:
        raise PermissionDenied("You cannot review your own identity.")
    # Owner resubmission reuses this row; the timestamp distinguishes the submitted document version.
    if submission.status != "pending" or submission.submitted_at.isoformat() != submitted_version:
        raise ValidationError("This submission changed or was already reviewed. Reload before reviewing it.")
    reason = reason.strip()
    if decision not in ("approved", "rejected") or (decision == "rejected" and not reason):
        raise ValidationError("Choose approval or rejection; rejection requires a reason.")
    submission.status = decision
    submission.rejection_reason = reason if decision == "rejected" else ""
    submission.reviewed_by = actor
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at"])
    return submission
