from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import OwnerVerification, User


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


class VerificationReviewForm(forms.ModelForm):
    submitted_version = forms.CharField(widget=forms.HiddenInput)

    class Meta:
        model = OwnerVerification
        fields = ("status", "rejection_reason")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["submitted_version"].initial = self.instance.submitted_at.isoformat()

    def clean(self):
        cleaned = super().clean()
        # Admin POSTs run in a transaction. Lock the record against owner resubmission.
        current = OwnerVerification.objects.select_for_update().get(pk=self.instance.pk)
        if (
            cleaned.get("submitted_version") != current.submitted_at.isoformat()
            or current.status != self.instance.status
        ):
            raise forms.ValidationError("This submission changed. Reload before reviewing it.")
        status = cleaned.get("status")
        if current.status != OwnerVerification.Status.PENDING and status != current.status:
            raise forms.ValidationError("Only pending submissions can be approved or rejected.")
        if status == OwnerVerification.Status.REJECTED and not cleaned.get("rejection_reason", "").strip():
            self.add_error("rejection_reason", "Explain why the document was rejected.")
        return cleaned


@admin.register(OwnerVerification)
class OwnerVerificationAdmin(admin.ModelAdmin):
    form = VerificationReviewForm
    list_display = ("user", "document_type", "status", "submitted_at", "reviewed_at")
    list_filter = ("status", "document_type")
    search_fields = ("user__email", "user__full_name")
    fields = ("user", "document_type", "document_download", "submitted_at", "submitted_version", "status", "rejection_reason", "reviewed_by", "reviewed_at")
    readonly_fields = ("user", "document_type", "document_download", "submitted_at", "reviewed_by", "reviewed_at")

    @admin.display(description="Identity document")
    def document_download(self, obj):
        return format_html('<a href="{}">Download document for review</a>', reverse("accounts:verification_document", args=[obj.pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if obj.status != OwnerVerification.Status.PENDING and (
            "status" in form.changed_data or "rejection_reason" in form.changed_data
        ):
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        if obj.status != OwnerVerification.Status.REJECTED:
            obj.rejection_reason = ""
        super().save_model(request, obj, form, change)
