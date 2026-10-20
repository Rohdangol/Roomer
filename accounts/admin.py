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
        ("Roomer", {"fields": ("full_name", "phone_number", "role", "email_verified_at", "verified_email")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Roomer", {"fields": ("email", "full_name", "phone_number", "role")}),
    )
    readonly_fields = ("email_verified_at", "verified_email")
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
        if current.status != OwnerVerification.Status.PENDING and (status != current.status or cleaned.get("rejection_reason", "") != current.rejection_reason):
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
        from .verification_services import review_owner_identity
        if {"status", "rejection_reason"} & set(form.changed_data):
            review_owner_identity(request.user, obj.pk, form.cleaned_data["status"],
                form.cleaned_data.get("rejection_reason", ""), form.cleaned_data["submitted_version"])
        obj.refresh_from_db()


from .models import TenantIdentityAttempt, TenantIdentityReview
from .verification_services import review_tenant_identity


class TenantReviewForm(forms.ModelForm):
    decision = forms.ChoiceField(choices=[("", "No decision"), ("approved", "Approve"), ("rejected", "Reject")], required=False)
    reason = forms.CharField(widget=forms.Textarea, required=False)

    class Meta:
        model = TenantIdentityAttempt
        fields = ()


@admin.register(TenantIdentityAttempt)
class TenantIdentityAdmin(admin.ModelAdmin):
    form = TenantReviewForm
    list_display = ("user", "document_type", "status", "submitted_at", "reviewed_at")
    list_filter = ("status", "document_type")
    readonly_fields = ("user", "document_type", "document_number", "issued_date", "document_downloads", "status", "submitted_at", "reviewed_by", "reviewed_at", "rejection_reason")
    fields = readonly_fields + ("decision", "reason")

    @admin.display(description="Private documents")
    def document_downloads(self, obj):
        return format_html('<a href="{}">Front</a> / <a href="{}">Back</a>', reverse("accounts:tenant_identity_document", args=[obj.pk, "front"]), reverse("accounts:tenant_identity_document", args=[obj.pk, "back"]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        decision = form.cleaned_data.get("decision")
        if decision:
            outcome = review_tenant_identity(request.user, obj.pk, decision, form.cleaned_data.get("reason", ""))
            request.tenant_review_outcome = outcome
            if outcome != "applied":
                from django.contrib import messages
                messages.error(request, "Review not applied: submission is already reviewed or rejection reason is missing.")
        obj.refresh_from_db()

    def response_change(self, request, obj):
        if getattr(request, "tenant_review_outcome", "applied") != "applied":
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)


@admin.register(TenantIdentityReview)
class TenantIdentityReviewAdmin(admin.ModelAdmin):
    list_display = ("attempt", "reviewer", "decision", "outcome", "created_at")
    readonly_fields = ("attempt", "reviewer", "decision", "rejection_reason", "outcome", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
