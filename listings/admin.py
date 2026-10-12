from django.contrib import admin

from .models import Amenity, ListingAmenity, ListingRevision, RoomImage, RoomListing


class InspectionAdmin(admin.ModelAdmin):
    # Workflow mutations belong in services; basic admin is inspection-only.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]


@admin.register(RoomListing)
class RoomListingAdmin(InspectionAdmin):
    list_display = ("id", "owner", "listing_status", "published_revision", "archived_at", "updated_at")
    list_filter = ("listing_status", "archive_source")


@admin.register(ListingRevision)
class ListingRevisionAdmin(InspectionAdmin):
    list_display = ("listing", "version", "title", "approval_status", "monthly_rent", "submitted_at")
    list_filter = ("approval_status", "room_type")


@admin.register(RoomImage)
class RoomImageAdmin(InspectionAdmin):
    fields = ("id", "revision", "stored_filename", "position", "created_at")

    def get_readonly_fields(self, request, obj=None):
        return self.fields

    @admin.display(description="Stored filename")
    def stored_filename(self, obj):
        return obj.image.name


admin.site.register(Amenity, InspectionAdmin)
admin.site.register(ListingAmenity, InspectionAdmin)
