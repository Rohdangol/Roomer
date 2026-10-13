from pathlib import Path
from mimetypes import guess_type
import logging

from django.conf import settings
from django.db import transaction
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_GET

from .models import TenantIdentityAttempt
from .verification_services import confirm_email, send_verification_email


@require_http_methods(["GET", "POST"])
def verify_email(request, token):
    error = None
    if request.method == "POST":
        try:
            confirm_email(token)
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            error = "This verification link is invalid, expired or replaced. Sign in to request another link."
        else:
            messages.success(request, "Email verified successfully. Please sign in if needed.")
            return redirect("accounts:login")
    return render(request, "accounts/verify_email.html", {"verification_error": error})


# Keep this view out of ATOMIC_REQUESTS so the service's commit callback finishes before the success message.
@transaction.non_atomic_requests
@login_required(login_url="accounts:login")
@require_POST
def resend_email(request):
    try:
        result = send_verification_email(request.user, request)
    except Exception as error:
        logging.getLogger("django.server").error("Verification resend failed: %s", type(error).__name__)
        messages.error(request, "Verification email could not be sent. Check the server terminal for the error type; wait before retrying.")
    else:
        sent_message = "Verification link printed to the runserver terminal (local console delivery); no inbox email was sent." if settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend" else "Verification link sent. Check your email."
        messages.info(request, {"sent": sent_message, "limited": "Please wait before requesting another email (60 seconds; at most 5 per hour).", "verified": "Your email is already verified."}[result])
    from .permissions import account_destination
    return redirect("accounts:tenant_profile" if request.user.role == "tenant" and not request.user.is_staff else account_destination(request.user))


@login_required(login_url="accounts:login")
@require_GET
def tenant_identity_document(request, pk, side):
    attempt = get_object_or_404(TenantIdentityAttempt, pk=pk)
    can_review = request.user.is_active and request.user.is_staff and (request.user.has_perm("accounts.view_tenantidentityattempt") or request.user.has_perm("accounts.change_tenantidentityattempt"))
    if attempt.user_id != request.user.pk and not can_review:
        raise Http404
    if side not in ("front", "back"):
        raise Http404
    document = getattr(attempt, f"{side}_document")
    try:
        stream = document.open("rb")
    except OSError:
        raise Http404
    response = FileResponse(stream, as_attachment=True, filename=f"identity-{side}{Path(document.name).suffix}", content_type=guess_type(document.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
