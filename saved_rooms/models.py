from django.conf import settings
from django.db import models


class SavedRoom(models.Model):
    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_rooms")
    listing = models.ForeignKey("listings.RoomListing", on_delete=models.CASCADE, related_name="saved_by_tenants")
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-saved_at", "-pk")
        constraints = [models.UniqueConstraint(fields=["tenant", "listing"], name="saved_room_tenant_listing_unique")]
        indexes = [models.Index(fields=["tenant", "saved_at"])]
