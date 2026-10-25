from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.views.decorators.debug import sensitive_post_parameters
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponseForbidden
from mimetypes import guess_type
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from preferences.models import TenantPreference
from preferences.services import save_tenant_preference
from .profile_forms import PersonalInformationForm, ProfilePictureForm, TextOnlyPreferenceForm, TenantIdentityForm


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def tenant_profile(request):
    if not request.user.is_active or request.user.is_staff or request.user.role != "tenant":
        return HttpResponseForbidden("This page is available to active tenants only.")
    # No target user ID is accepted: all reads and writes belong to the session user.
    preference = TenantPreference.objects.filter(tenant=request.user).prefetch_related("amenity_links__amenity").first()
    instance = preference or TenantPreference(tenant=request.user)
    action = request.POST.get("action") if request.method == "POST" else None
    information_form = PersonalInformationForm(request.POST if request.method == "POST" and action != "preferences" else None, instance=request.user)
    picture_form = ProfilePictureForm(request.POST if action == "picture" else None, request.FILES if action == "picture" else None, instance=request.user)
    preference_form = TextOnlyPreferenceForm(request.POST if action == "preferences" else None, instance=instance)
    from .models import TenantIdentityAttempt
    from .verification_services import email_is_verified, submit_tenant_identity
    identity = TenantIdentityAttempt.objects.filter(user=request.user).first()
    identity_form = TenantIdentityForm(request.POST if action == "identity" else None, request.FILES if action == "identity" else None, instance=TenantIdentityAttempt(user=request.user))
    if request.method == "POST":
        if action == "identity" and identity_form.is_valid():
            try:
                submit_tenant_identity(request.user, identity_form.cleaned_data)
            except ValidationError as error:
                identity_form.add_error(None, error.messages)
            else:
                messages.success(request, "Identity submitted for admin review.")
                return redirect("accounts:tenant_profile")
        if action == "picture" and picture_form.is_valid():
            user = picture_form.save(commit=False)
            # A new randomized file avoids overwriting a picture another request is reading.
            user.save(update_fields=["profile_picture"])
            messages.success(request, "Profile picture updated.")
            return redirect("accounts:tenant_profile")
        if action == "information" and information_form.is_valid():
            user = information_form.save(commit=False)
            # Save only permitted fields; concurrent permission/email changes are untouched.
            user.save(update_fields=["full_name", "phone_number"])
            messages.success(request, "Personal information updated.")
            return redirect("accounts:tenant_profile")
        if action == "preferences" and preference_form.is_valid():
            details = {name: preference_form.cleaned_data[name] for name in ("preferred_location", "latitude", "longitude", "preferred_room_type", "maximum_budget", "preferred_furnishing")}
            try:
                save_tenant_preference(request.user, details, amenity_ids=[amenity.pk for amenity in preference_form.cleaned_data["amenities"]], coordinates_selected=preference_form.cleaned_data.get("coordinates_selected", False))
            except ValidationError as error:
                preference_form.add_error(None, error.messages)
            else:
                messages.success(request, "Room preferences updated.")
                return redirect("accounts:tenant_profile")
        if action not in ("information", "preferences", "picture", "identity"):
            information_form.add_error(None, "Choose a supported profile action.")
    # Read fresh values for summaries: ModelForm validation can mutate its instance.
    request.user.refresh_from_db()
    preference = TenantPreference.objects.filter(tenant=request.user).prefetch_related("amenity_links__amenity").first()
    return render(request, "accounts/tenant_profile.html", {"identity": identity, "identity_form": identity_form, "identity_history": TenantIdentityAttempt.objects.filter(user=request.user), "email_verified": email_is_verified(request.user), "verification_completed": int(email_is_verified(request.user)) + int(bool(identity and identity.status == "approved")), "picture_form": picture_form, "edit_picture": action == "picture", "information_form": information_form, "preference_form": preference_form, "preference": preference, "edit_information": action == "information", "edit_preferences": action == "preferences"})


@login_required(login_url="accounts:login")
@require_http_methods(["GET"])
def profile_picture(request):
    if not request.user.is_active or request.user.is_staff or request.user.role != "tenant":
        return HttpResponseForbidden("This page is available to active tenants only.")
    # No user/file identifier is accepted, preventing access to another account's upload.
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


@sensitive_post_parameters()
@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def tenant_password_change(request):
    if not request.user.is_active or request.user.is_staff or request.user.role != "tenant":
        return HttpResponseForbidden("This page is available to active tenants only.")
    # Bind only the session user; Django validates the old password and new password rules.
    form = PasswordChangeForm(request.user, request.POST if request.method == "POST" else None)
    form.fields["old_password"].label = "Current Password"
    form.fields["new_password1"].label = "New Password"
    form.fields["new_password2"].label = "Confirm New Password"
    if request.method == "POST" and form.is_valid():
        user = form.save()
        # Rotate this session's authentication hash so changing passwords does not sign it out.
        update_session_auth_hash(request, user)
        messages.success(request, "Your password has been changed.")
        return redirect("accounts:tenant_profile")
    return render(request, "accounts/password_change.html", {
        "form": form, "profile_url": "accounts:tenant_profile",
        "password_url": "accounts:tenant_password_change",
    })
