from mimetypes import guess_type

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters

from listings.models import RoomListing
from rentals.models import RentalAgreement, RentalRequest
from listings.services import require_owner
from .models import OwnerVerification
from .profile_forms import PersonalInformationForm, ProfilePictureForm
from .verification_services import email_is_verified


@sensitive_post_parameters()
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def password_change(request):
    # Password recovery settings remain available before email or identity verification.
    require_owner(request.user)
    form = PasswordChangeForm(request.user, request.POST if request.method == "POST" else None)
    form.fields["old_password"].label = "Current Password"
    form.fields["new_password1"].label = "New Password"
    form.fields["new_password2"].label = "Confirm New Password"
    if request.method == "POST" and form.is_valid():
        user = form.save()
        # Keep this session authenticated after Django stores the new password hash.
        update_session_auth_hash(request, user)
        messages.success(request, "Your password has been changed.")
        return redirect("accounts:owner_profile")
    return render(request, "accounts/owner_password_change.html", {"form": form})


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def profile(request):
    require_owner(request.user)
    # No verification gate: owners must be able to correct their profile and recover verification.
    action = request.POST.get("action") if request.method == "POST" else None
    information_form = PersonalInformationForm(request.POST if request.method == "POST" and action != "picture" else None,
        instance=request.user)
    picture_form = ProfilePictureForm(request.POST if action == "picture" else None,
        request.FILES if action == "picture" else None, instance=request.user)
    if request.method == "POST":
        if action == "information" and information_form.is_valid():
            user = information_form.save(commit=False)
            # Narrow writes preserve email, role and verification changes from other requests.
            user.save(update_fields=["full_name", "phone_number"])
            messages.success(request, "Personal information updated.")
            return redirect("accounts:owner_profile")
        if action == "picture" and picture_form.is_valid():
            user = picture_form.save(commit=False)
            # Reuse randomized private storage; never overwrite a photo being read.
            user.save(update_fields=["profile_picture"])
            messages.success(request, "Profile picture updated.")
            return redirect("accounts:owner_profile")
        if action not in ("information", "picture"):
            information_form.add_error(None, "Choose a supported profile action.")
    # ModelForm validation can mutate its instance even when the submitted form is invalid.
    request.user.refresh_from_db()
    identity = OwnerVerification.objects.filter(user=request.user).first()
    email_verified = email_is_verified(request.user)
    return render(request, "accounts/owner_profile.html", {
        "information_form": information_form, "picture_form": picture_form,
        "edit_information": request.method == "POST" and action != "picture", "edit_picture": action == "picture",
        "identity": identity, "email_verified": email_verified,
        "pending_requests": RentalRequest.objects.filter(listing__owner=request.user, status="pending").count(),
        "active_rentals": RentalAgreement.objects.filter(owner=request.user, status="active").count(),
        "verification_completed": int(email_verified) + int(bool(identity and identity.status == "approved")),
        "active_listings": RoomListing.objects.filter(owner=request.user, archived_at__isnull=True,
            listing_status=RoomListing.Status.AVAILABLE, published_revision__approval_status="approved").count(),
    })


@login_required(login_url="accounts:login")
@require_GET
def profile_picture(request):
    require_owner(request.user)
    # Session user only: neither a target user ID nor a file path is accepted.
    picture = request.user.profile_picture
    if not picture:
        raise Http404
    try:
        stream = picture.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    response = FileResponse(stream, content_type=guess_type(picture.name)[0] or "application/octet-stream")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
