from pathlib import Path

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.utils import timezone

from .forms import EmailLoginForm, OwnerVerificationForm, RegistrationForm
from .models import OwnerVerification, User
from .permissions import account_destination, owner_needs_verification


def register(request):
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            # Roll back a failed insert before querying for a concurrent signup.
            with transaction.atomic():
                registered_user = form.save()
        except IntegrityError:
            if not User.objects.filter(email__iexact=form.cleaned_data["email"]).exists():
                raise
            form.add_error("email", "An account with this email address already exists.")
        else:
            from .verification_services import send_verification_email
            try:
                send_verification_email(registered_user, request)
            except Exception:
                messages.warning(request, "Account created. Email delivery failed; sign in to request another verification link.")
            else:
                messages.info(request, "Check your email for the verification link (valid for 24 hours).")
            messages.success(request, "Account created successfully. Please sign in.")
            return redirect("accounts:login")
    return render(request, "accounts/register.html", {"form": form})


def sign_in(request):
    if request.user.is_authenticated:
        return redirect(account_destination(request.user))
    form = EmailLoginForm(
        request=request, data=request.POST if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        # Use a fixed destination rather than accepting an untrusted next URL.
        return redirect(account_destination(request.user))
    return render(request, "accounts/login.html", {"form": form})


@require_POST
def sign_out(request):
    # POST and CSRF protection prevent other pages from triggering a sign-out.
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("accounts:login")


@login_required(login_url="accounts:login")
def owner_area(request):
    if request.user.is_staff or request.user.role != User.Role.OWNER:
        return HttpResponseForbidden("This page is available to owners only.")
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    return render(request, "accounts/role_home.html", {"page_title": "Owner area"})


@login_required(login_url="accounts:login")
def admin_area(request):
    if not request.user.is_active or not request.user.is_staff:
        return HttpResponseForbidden("This page is available to admin staff only.")
    # Delegate actual admin screens and model permissions to Django admin.
    return redirect("admin:index")


@login_required(login_url="accounts:login")
def verification(request):
    if request.user.role != User.Role.OWNER:
        return redirect("home")
    submission = OwnerVerification.objects.filter(user=request.user).first()
    form = OwnerVerificationForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
    )
    if request.method == "POST":
        # Serialize submissions for this owner; pending/approved documents cannot be replaced.
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            submission = OwnerVerification.objects.select_for_update().filter(user=request.user).first()
            if submission and submission.status != OwnerVerification.Status.REJECTED:
                messages.error(request, "Your submission cannot be changed while pending or approved.")
                return redirect("accounts:verification")
            if form.is_valid():
                updated = form.save(commit=False)
                if submission:
                    updated.pk = submission.pk
                updated.user = request.user
                updated.submitted_at = timezone.now()
                updated.status = OwnerVerification.Status.PENDING
                updated.reviewed_at = None
                updated.reviewed_by = None
                updated.rejection_reason = ""
                updated.save()
                messages.success(request, "Verification submitted. Please wait for admin approval.")
                return redirect("accounts:verification")
    return render(request, "accounts/verification.html", {"submission": submission, "form": form})


@login_required(login_url="accounts:login")
def verification_document(request, pk):
    submission = OwnerVerification.objects.filter(pk=pk).first()
    can_review = request.user.is_staff and (
        request.user.has_perm("accounts.view_ownerverification")
        or request.user.has_perm("accounts.change_ownerverification")
    )
    # Do not disclose whether another user's identity document exists.
    if submission is None or (submission.user_id != request.user.pk and not can_review):
        raise Http404
    try:
        document = submission.document.open("rb")
    except FileNotFoundError:
        raise Http404
    response = FileResponse(
        document, as_attachment=True,
        filename="identity-document" + Path(submission.document.name).suffix,
        content_type="application/octet-stream",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
