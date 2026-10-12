from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from accounts.models import User
from .services import create_notification, mark_notifications_read


class NotificationTests(TestCase):
    def test_recipient_scope_and_mark_all_read(self):
        user = User.objects.create_user(username="tenant", email="tenant@example.com")
        other = User.objects.create_user(username="other", email="other@example.com")
        first = create_notification(user, "Notice", "Listing review completed.")
        second = create_notification(other, "Notice", "Other user's notice.")
        self.assertEqual(mark_notifications_read(user, second.pk), 0)
        self.assertEqual(mark_notifications_read(user), 1)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_read)
        self.assertFalse(second.is_read)
        self.assertEqual(mark_notifications_read(user), 0)
        user.is_active = False
        user.save()
        with self.assertRaises(PermissionDenied):
            mark_notifications_read(user)
        with self.assertRaises(ValidationError):
            create_notification(other, " ", "message")
