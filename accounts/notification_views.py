from urllib.parse import urlsplit

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.http import require_GET, require_POST

from notifications.models import Notification
from notifications.services import mark_notifications_read


@login_required(login_url="accounts:login")
@require_POST
def mark_read(request, pk=None, expected_role="tenant"):
    if expected_role == "admin":
        from .admin_dashboard_views import require_staff
        require_staff(request.user)
    elif not request.user.is_active or request.user.is_staff or request.user.role != expected_role:
        return HttpResponseForbidden(f"This page is available to active {expected_role}s only.")
    if pk is not None:
        # Do not reveal whether another user's notification exists.
        get_object_or_404(Notification, pk=pk, user=request.user)
    mark_notifications_read(request.user, notification_id=pk)
    destination = reverse({"admin": "accounts:admin_notifications", "owner": "accounts:owner_notifications"}.get(expected_role, "accounts:tenant"))
    admin_destinations = {
        "accounts:admin", "accounts:admin_profile", "accounts:admin_notifications",
        "accounts:admin_users", "accounts:admin_user_details", "accounts:admin_listings",
        "accounts:admin_listing_details", "accounts:admin_agreements", "accounts:admin_agreement_details_layout",
        "accounts:admin_agreement_details", "accounts:admin_agreement_version",
    }
    owner_destinations = {
        "accounts:owner", "accounts:owner_profile", "accounts:owner_notifications",
        "accounts:owner_listings", "accounts:owner_listing_details", "accounts:owner_edit_listing",
        "accounts:owner_add_listing", "accounts:owner_requests", "accounts:owner_request_details_layout",
        "accounts:owner_agreements", "accounts:owner_agreement_details_layout", "accounts:verification",
        "accounts:owner_request_details",
        "accounts:owner_agreement_details", "accounts:owner_agreement_version", "accounts:owner_agreement_prepare",
    }
    tenant_destinations = {
        "accounts:tenant", "accounts:find_rooms", "accounts:room_details", "accounts:saved_rooms",
        "accounts:tenant_profile", "accounts:my_requests", "accounts:my_agreements",
        "accounts:request_details", "accounts:request_create",
        "accounts:agreement_details", "accounts:agreement_version",
    }
    allowed_destinations = {"admin": admin_destinations, "owner": owner_destinations}.get(expected_role, tenant_destinations)
    try:
        parts = urlsplit(request.POST.get("return_to", ""))
        if not parts.scheme and not parts.netloc and resolve(parts.path).view_name in allowed_destinations:
            destination = parts.path + ("?" + parts.query if parts.query else "")
    except (ValueError, Resolver404):
        pass
    return redirect(destination)


@login_required(login_url="accounts:login")
@require_GET
def owner_notifications(request):
    from listings.services import require_owner
    require_owner(request.user)
    # Verification notices must remain accessible while an owner is awaiting approval.
    return notification_page(request, "accounts/owner_notifications.html")


def notification_page(request, template):
    # Called only after role/staff authorization; every record is scoped to its recipient.
    notifications = Notification.objects.filter(user=request.user).order_by("-created_at", "-pk")
    return render(request, template, {
        "notifications": notifications, "unread_count": notifications.filter(is_read=False).count(),
    })


@login_required(login_url="accounts:login")
@require_GET
def admin_notifications(request):
    from .admin_dashboard_views import require_staff
    require_staff(request.user)
    return notification_page(request, "custom_admin/notifications.html")
