from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User
from listings.models import Amenity
from .models import PreferredAmenity, TenantPreference
from .services import save_tenant_preference


class PreferenceTests(TestCase):
    def setUp(self):
        self.tenant = User.objects.create_user(username="tenant", email="tenant@example.com")
        self.owner = User.objects.create_user(username="owner", email="owner@example.com", role="owner")
        self.details = dict(preferred_location=" Baneshwor ", latitude="27.700000", longitude="85.300000", maximum_budget="15000.00", preferred_room_type="single_room", preferred_furnishing="furnished")

    def test_optional_amenities_and_atomic_replacement(self):
        preference = save_tenant_preference(self.tenant, self.details)
        self.assertEqual(preference.preferred_location, "Baneshwor")
        self.assertEqual(preference.amenity_links.count(), 0)
        amenity = Amenity.objects.first()
        save_tenant_preference(self.tenant, self.details, [amenity.pk])
        self.assertEqual(preference.amenity_links.count(), 1)
        with self.assertRaises(ValidationError):
            save_tenant_preference(self.tenant, self.details, [999999])
        self.assertEqual(preference.amenity_links.count(), 1)
        save_tenant_preference(self.tenant, self.details)
        self.assertEqual(preference.amenity_links.count(), 0)

    def test_roles_required_fields_and_constraints(self):
        with self.assertRaises(PermissionDenied):
            save_tenant_preference(self.owner, self.details)
        with self.assertRaises(ValidationError):
            save_tenant_preference(self.tenant, {"maximum_budget": 100})
        preference = save_tenant_preference(self.tenant, self.details)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TenantPreference.objects.filter(pk=preference.pk).update(maximum_budget=0)
        amenity = Amenity.objects.first()
        PreferredAmenity.objects.create(preference=preference, amenity=amenity)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PreferredAmenity.objects.create(preference=preference, amenity=amenity)
