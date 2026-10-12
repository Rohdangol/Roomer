from .models import OwnerVerification, User


def owner_needs_verification(user):
    # Check current database status so approval/rejection affects existing sessions too.
    return (
        user.is_authenticated
        and not user.is_staff
        and user.role == User.Role.OWNER
        and not OwnerVerification.objects.filter(user=user, status=OwnerVerification.Status.APPROVED).exists()
    )


def account_destination(user):
    # Staff access is a Django permission flag, never a publicly selectable role.
    if user.is_staff:
        return "accounts:admin"
    if owner_needs_verification(user):
        return "accounts:verification"
    if user.role == User.Role.OWNER:
        return "accounts:owner"
    if user.role == User.Role.TENANT:
        return "accounts:tenant"
    return "home"
