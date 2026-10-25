from django.shortcuts import redirect, render
from django.http import HttpResponse
from django.views.decorators.http import require_GET

from accounts.permissions import account_destination, owner_needs_verification


@require_GET
def empty_page(request):
    return HttpResponse('<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>Roomer</title></head><body style="background:white"></body></html>')


def home(request):
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    return render(request, "core/home.html", {
        "account_destination": account_destination(request.user) if request.user.is_authenticated else None,
    })
