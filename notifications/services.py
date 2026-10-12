from django.core.exceptions import PermissionDenied

from .models import Notification


def create_notification(recipient, title, message):
    # Internal service only: workflow callers create this inside their transaction.
    notification = Notification(user=recipient, title=title, message=message)
    notification.full_clean()
    notification.save()
    return notification


def mark_notifications_read(actor, notification_id=None):
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("Sign in to manage your notifications.")
    notifications = Notification.objects.filter(user=actor, is_read=False)
    if notification_id is not None:
        notifications = notifications.filter(pk=notification_id)
    # Filtering by recipient also protects mark-all-read from changing others' records.
    return notifications.update(is_read=True)
