from django.contrib import admin

from listings.admin import InspectionAdmin
from .models import PreferredAmenity, TenantPreference

admin.site.register(TenantPreference, InspectionAdmin)
admin.site.register(PreferredAmenity, InspectionAdmin)
