from urllib.parse import urlsplit

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.http import require_POST

from notifications.models import Notification
from notifications.services import mark_notifications_read


@login_required(login_url="accounts:login")
@require_POST
def mark_read(request, pk=None):
    if not request.user.is_active or request.user.is_staff or request.user.role != "tenant":
        return HttpResponseForbidden("This page is available to active tenants only.")
    if pk is not None:
        # Do not reveal whether another user's notification exists.
        get_object_or_404(Notification, pk=pk, user=request.user)
    mark_notifications_read(request.user, notification_id=pk)
    destination = reverse("accounts:tenant")
    try:
        parts = urlsplit(request.POST.get("return_to", ""))
        if not parts.scheme and not parts.netloc and resolve(parts.path).view_name in {
            "accounts:tenant", "accounts:find_rooms", "accounts:room_details",
            "accounts:saved_rooms", "accounts:tenant_profile", "accounts:my_requests", "accounts:my_agreements",
        }:
            destination = parts.path + ("?" + parts.query if parts.query else "")
    except (ValueError, Resolver404):
        pass
    return redirect(destination)
