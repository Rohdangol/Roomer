from accounts.models import OwnerVerification, User
from accounts.permissions import account_destination


def public_navigation(request):
    if not request.user.is_authenticated:
        return {}
    # Navigation reflects server-side permissions; hiding a link never grants access.
    submission = None
    if request.user.role == User.Role.OWNER and not request.user.is_staff:
        submission = OwnerVerification.objects.filter(user=request.user).first()
    from accounts.verification_services import email_is_verified
    context = {
        "registration_email_unverified": not email_is_verified(request.user),
        "navigation_destination": account_destination(request.user),
        "navigation_verification": submission,
    }

    if request.user.is_active and (request.user.is_staff or request.user.role in (User.Role.TENANT, User.Role.OWNER)):
        from notifications.models import Notification
        notifications = Notification.objects.filter(user=request.user).order_by("-created_at", "-pk")
        notification_role = "admin" if request.user.is_staff else request.user.role
        context[f"{notification_role}_notifications"] = notifications
        context[f"{notification_role}_unread_count"] = notifications.filter(is_read=False).count()
    return context
