from django.contrib import admin

from .models import AgreementReview, AgreementTerms, RentalAgreement, RentalRequest


@admin.register(RentalRequest)
class RentalRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "listing", "status", "requested_at")
    list_filter = ("status",)

    # Historical records are inspected here; mutations must use authorized workflow services.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RentalAgreement)
class RentalAgreementAdmin(RentalRequestAdmin):
    list_display = ("id", "tenant", "owner", "listing", "status")


@admin.register(AgreementTerms)
class AgreementTermsAdmin(RentalRequestAdmin):
    list_display = ("id", "agreement", "version", "sent_at", "tenant_accepted_at", "owner_accepted_at")
    list_filter = ()

    def has_view_permission(self, request, obj=None):
        # Terms contain participant snapshots and require agreement access as well.
        return request.user.has_perm("rentals.view_rentalagreement") and super().has_view_permission(request, obj)


@admin.register(AgreementReview)
class AgreementReviewAdmin(RentalRequestAdmin):
    list_display = ("id", "terms", "reviewer", "decision", "created_at")
    list_filter = ("decision",)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("rentals.view_rentalagreement") and super().has_view_permission(request, obj)
