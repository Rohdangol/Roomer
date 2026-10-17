from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_GET


@login_required(login_url="accounts:login")
@require_GET
def my_requests(request):
    if not request.user.is_active or request.user.is_staff or request.user.role != "tenant":
        return HttpResponseForbidden("This page is available to active tenants only.")
    # The rentals lifecycle is not agreed yet; do not fabricate records or status counts.
    return render(request, "accounts/my_requests.html", {"requests_available": False})
