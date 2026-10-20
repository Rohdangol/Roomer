from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from .admin_dashboard_views import private_photo, require_staff
from .profile_forms import PersonalInformationForm, ProfilePictureForm


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def profile(request):
    require_staff(request.user)
    # No target ID: these allowlisted forms can update only the signed-in staff account.
    action = request.POST.get("action") if request.method == "POST" else None
    information_form = PersonalInformationForm(
        request.POST if request.method == "POST" and action != "picture" else None, instance=request.user)
    picture_form = ProfilePictureForm(request.POST if action == "picture" else None,
        request.FILES if action == "picture" else None, instance=request.user)
    if request.method == "POST":
        if action == "information" and information_form.is_valid():
            person = information_form.save(commit=False)
            # Narrow writes cannot change email, privileges, password or account status.
            person.save(update_fields=["full_name", "phone_number"])
            messages.success(request, "Personal information updated.")
            return redirect("accounts:admin_profile")
        if action == "picture" and picture_form.is_valid():
            person = picture_form.save(commit=False)
            # Existing validation and randomized private storage apply to staff photos too.
            person.save(update_fields=["profile_picture"])
            messages.success(request, "Profile picture updated.")
            return redirect("accounts:admin_profile")
        if action not in ("information", "picture"):
            information_form.add_error(None, "Choose a supported profile action.")
    # Invalid ModelForms can mutate their instance; keep summaries and shared header accurate.
    request.user.refresh_from_db()
    return render(request, "custom_admin/profile.html", {
        "information_form": information_form, "picture_form": picture_form,
        "edit_information": request.method == "POST" and action != "picture", "edit_picture": action == "picture",
    })


@login_required(login_url="accounts:login")
@require_GET
def profile_picture(request):
    require_staff(request.user)
    # Self-only delivery, including staff without permission to browse other users.
    return private_photo(request.user.profile_picture)
