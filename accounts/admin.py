from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class RoomerUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Roomer", {"fields": ("full_name", "phone_number", "role")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Roomer", {"fields": ("email", "full_name", "phone_number", "role")}),
    )
    list_display = ("email", "full_name", "role", "is_staff")
    list_display_links = ("email",)
    list_filter = UserAdmin.list_filter + ("role",)
