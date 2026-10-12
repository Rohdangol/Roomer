from django.contrib import messages
from django.contrib.auth import login, logout
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .forms import EmailLoginForm, RegistrationForm
from .models import User


def register(request):
    form = RegistrationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            # Roll back a failed insert before querying for a concurrent signup.
            with transaction.atomic():
                form.save()
        except IntegrityError:
            if not User.objects.filter(email__iexact=form.cleaned_data["email"]).exists():
                raise
            form.add_error("email", "An account with this email address already exists.")
        else:
            messages.success(request, "Account created successfully. Please sign in.")
            return redirect("accounts:login")
    return render(request, "accounts/register.html", {"form": form})


def sign_in(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = EmailLoginForm(
        request=request, data=request.POST if request.method == "POST" else None,
    )
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        # Use a fixed destination rather than accepting an untrusted next URL.
        return redirect("home")
    return render(request, "accounts/login.html", {"form": form})


@require_POST
def sign_out(request):
    # POST and CSRF protection prevent other pages from triggering a sign-out.
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("accounts:login")
