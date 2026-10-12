from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from listings.choices import Furnishing, RoomType


class TenantPreference(models.Model):
    tenant = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="room_preference")
    preferred_location = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    maximum_budget = models.DecimalField(max_digits=12, decimal_places=2)
    preferred_room_type = models.CharField(max_length=16, choices=RoomType.choices)
    preferred_furnishing = models.CharField(max_length=16, choices=Furnishing.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(maximum_budget__gt=0), name="preference_positive_budget"),
            models.CheckConstraint(condition=Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180), name="preference_valid_coordinates"),
            models.CheckConstraint(condition=Q(preferred_room_type__in=RoomType.values, preferred_furnishing__in=Furnishing.values), name="preference_valid_choices"),
        ]

    def clean(self):
        self.preferred_location = self.preferred_location.strip()
        if not self.preferred_location:
            raise ValidationError({"preferred_location": "Enter a location."})
        if self.tenant.role != "tenant":
            raise ValidationError({"tenant": "Preferences belong to tenants only."})


class PreferredAmenity(models.Model):
    preference = models.ForeignKey(TenantPreference, on_delete=models.CASCADE, related_name="amenity_links")
    amenity = models.ForeignKey("listings.Amenity", on_delete=models.PROTECT, related_name="preference_links")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["preference", "amenity"], name="preferred_amenity_unique")]
