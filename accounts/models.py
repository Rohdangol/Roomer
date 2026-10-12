from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.db.models.functions import Lower


class UserManager(DjangoUserManager):
    @classmethod
    def normalize_email(cls, email):
        # Treat the entire email address consistently for signup and future login.
        return (email or "").strip().lower()


class User(AbstractUser):
    class Role(models.TextChoices):
        TENANT = "tenant", "Tenant"
        OWNER = "owner", "Owner"

    # A Roomer role describes how a user uses the site; admin permissions stay separate.
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TENANT)
    full_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(unique=True)

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            # Protect uniqueness even when a database write bypasses save().
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
        ]

    def save(self, *args, **kwargs):
        self.email = type(self).objects.normalize_email(self.email)
        return super().save(*args, **kwargs)
