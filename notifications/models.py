from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=["user", "is_read", "created_at"])]

    def clean(self):
        for name in ("title", "message"):
            value = getattr(self, name).strip()
            if not value:
                raise ValidationError({name: "This field is required."})
            setattr(self, name, value)

    def __str__(self):
        return self.title
