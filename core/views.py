from django.shortcuts import redirect, render

from accounts.permissions import account_destination, owner_needs_verification


def home(request):
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    return render(request, "core/home.html", {
        "account_destination": account_destination(request.user) if request.user.is_authenticated else None,
    })
