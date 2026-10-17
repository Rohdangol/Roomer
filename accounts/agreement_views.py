from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_GET


@login_required(login_url="accounts:login")
@require_GET
def my_agreements(request):
    if not request.user.is_active or request.user.is_staff or request.user.role != "tenant":
        return HttpResponseForbidden("This page is available to active tenants only.")
    # No agreement backend exists: do not infer counts, statuses or confirmation data.
    return render(request, "accounts/my_agreements.html", {"agreements_available": False})
