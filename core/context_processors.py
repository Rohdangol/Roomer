from accounts.models import OwnerVerification, User
from accounts.permissions import account_destination


def public_navigation(request):
    if not request.user.is_authenticated:
        return {}
    # Navigation reflects server-side permissions; hiding a link never grants access.
    submission = None
    if request.user.role == User.Role.OWNER and not request.user.is_staff:
        submission = OwnerVerification.objects.filter(user=request.user).first()
    return {
        "navigation_destination": account_destination(request.user),
        "navigation_verification": submission,
    }
