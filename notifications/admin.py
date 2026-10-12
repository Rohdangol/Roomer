from django.contrib import admin

from listings.admin import InspectionAdmin
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(InspectionAdmin):
    list_display = ("user", "title", "is_read", "created_at")
    list_filter = ("is_read",)
