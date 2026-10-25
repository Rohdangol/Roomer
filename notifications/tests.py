from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.test import Client
from django.urls import reverse

from accounts.models import User
from .services import create_notification, mark_notifications_read


class NotificationTests(TestCase):
    def test_async_read_actions_are_recipient_scoped_for_every_role(self):
        for role in ("tenant", "owner", "admin"):
            with self.subTest(role=role):
                user = User.objects.create_user(username=f"notification-{role}", email=f"{role}@notification.example",
                    role="owner" if role == "owner" else "tenant", is_staff=role == "admin")
                other = User.objects.create_user(username=f"other-{role}", email=f"other-{role}@notification.example")
                first = create_notification(user, "First", "First notice")
                second = create_notification(user, "Second", "Second notice")
                foreign = create_notification(other, "Private", "Foreign notice")
                prefix = "" if role == "tenant" else role + "_"
                individual = "accounts:" + ("notification_read" if role == "tenant" else prefix + "notification_read")
                all_read = "accounts:" + ("notifications_read_all" if role == "tenant" else prefix + "notifications_read_all")
                self.client.force_login(user, backend="accounts.backends.EmailBackend")
                self.assertEqual(self.client.get(reverse(individual, args=[first.pk])).status_code, 405)
                self.assertEqual(self.client.post(reverse(individual, args=[foreign.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 404)
                response = self.client.post(reverse(individual, args=[first.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["unread_count"], 1)
                self.assertEqual(response.json()["read_ids"], [first.pk])
                response = self.client.post(reverse(all_read), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(response.json()["unread_count"], 0)
                self.assertEqual(set(response.json()["read_ids"]), {first.pk, second.pk})
                foreign.refresh_from_db()
                self.assertFalse(foreign.is_read)
                strict = Client(enforce_csrf_checks=True)
                strict.force_login(user, backend="accounts.backends.EmailBackend")
                self.assertEqual(strict.post(reverse(all_read), HTTP_X_REQUESTED_WITH="XMLHttpRequest").status_code, 403)
                self.assertEqual(self.client.post(reverse(all_read)).status_code, 302)

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
