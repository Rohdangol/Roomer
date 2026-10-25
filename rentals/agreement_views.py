from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Count, Exists, OuterRef, Q
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.admin_dashboard_views import require_staff
from .agreement_services import (complete_agreement, confirm_agreement, finalize_agreement, local_today,
    prepare_agreement, scoped_agreements, send_agreement, request_agreement_changes, review_agreement)
from .forms import AgreementActionForm, AgreementTermsForm, AgreementReasonForm
from .models import RentalAgreement
from .views import request_access, scoped_requests


def agreement_access(request, role):
    if role == "admin":
        require_staff(request.user)
        if not request.user.has_perm("rentals.view_rentalagreement"):
            raise PermissionDenied("Agreement view permission is required.")
    else:
        return request_access(request, role == "owner")


def detail_name(role):
    return {"owner": "accounts:owner_agreement_details", "admin": "accounts:admin_agreement_details"}.get(role, "accounts:agreement_details")


@login_required(login_url="accounts:login")
@require_GET
def agreement_list(request, role="tenant"):
    response = agreement_access(request, role)
    if response:
        return response
    records = scoped_agreements(request.user).select_related("current_terms")
    if role == "owner":
        from accounts.models import TenantIdentityAttempt
        # The badge is actual identity approval, independent of agreement/email consent.
        records = records.annotate(tenant_identity_verified=Exists(TenantIdentityAttempt.objects.filter(
            user_id=OuterRef("tenant_id"), status="approved")))
    query = request.GET.get("q", "").strip()[:150] if role == "admin" else ""
    if query:
        condition = Q(current_terms__tenant_snapshot__full_name__icontains=query) | Q(current_terms__owner_snapshot__full_name__icontains=query)
        if query.isdecimal():
            condition |= Q(pk=int(query))
        records = records.filter(condition)
    # These are presentation buckets only; stored workflow states remain precise.
    groups = {
        "pending": ["draft", "awaiting_tenant", "changes_requested", "pending_admin", "scheduled", "pending"],
        "active": ["active"],
        "completed": ["completed"],
    }
    status = request.GET.get("status", "all")
    if status not in {"all", *groups}:
        raise Http404("Unknown agreement filter.")
    counts = dict(records.values("status").annotate(total=Count("pk")).values_list("status", "total"))
    filters = [{"value": "all", "label": "All", "count": sum(counts.values())}]
    filters += [{"value": value, "label": value.title(), "count": sum(counts.get(state, 0) for state in states)}
        for value, states in groups.items()]
    filtered = records if status == "all" else records.filter(status__in=groups[status])
    context = {"status": status, "status_filters": filters,
        "page_obj": Paginator(filtered, 3).get_page(request.GET.get("page"))}
    for agreement in context["page_obj"]:
        agreement.display_terms = visible_terms(agreement, request.user)
    context.update(role=role, owner_view=role != "tenant", query=query,
        list_url=reverse({"owner": "accounts:owner_agreements", "admin": "accounts:admin_agreements"}.get(role, "accounts:my_agreements")))
    template = {"owner": "accounts/owner_agreements.html", "admin": "custom_admin/agreements.html"}.get(role, "accounts/my_agreements.html")
    return render(request, template, context)


def visible_terms(agreement, user):
    if not user.is_staff and user.role == "tenant":
        # Keep an Owner's replacement draft private until it is sent. The Tenant sees the last sent version.
        return agreement.versions.filter(sent_at__isnull=False).order_by("-version").first()
    return agreement.current_terms


@login_required(login_url="accounts:login")
@require_GET
def agreement_detail(request, pk, role="tenant", version=None):
    response = agreement_access(request, role)
    if response:
        return response
    agreement = get_object_or_404(scoped_agreements(request.user).select_related("current_terms"), pk=pk)
    terms = visible_terms(agreement, request.user)
    versions = agreement.versions.all()
    if role == "tenant":
        versions = versions.filter(sent_at__isnull=False)
    if version is not None:
        terms = get_object_or_404(versions, version=version)
    current = terms.pk == agreement.current_terms_id
    modern = agreement.workflow_version == 2
    can_review = role == "admin" and all(request.user.has_perm(p) for p in (
        "rentals.change_rentalagreement", "rentals.approve_rentalagreement"))
    # A Tenant can read prior sent versions while an unsent replacement is private.
    reviews = agreement.versions.filter(pk__in=versions.values("pk")).prefetch_related("reviews__reviewer")
    context = {"agreement": agreement, "terms": terms, "role": role, "versions": versions,
        "review_versions": reviews, "current_version": current, "today": local_today(),
        "can_confirm": modern and role == "tenant" and current and agreement.status == "awaiting_tenant" and terms.sent_at and not terms.tenant_accepted_at,
        "can_edit": modern and role == "owner" and current and agreement.status in ("draft", "changes_requested"),
        "can_send": modern and role == "owner" and agreement.status == "draft" and current and not terms.sent_at,
        "can_review": modern and can_review and current and agreement.status == "pending_admin",
        "can_complete": current and agreement.status == "active" and terms.end_date and
            (local_today() > terms.end_date if modern else local_today() >= terms.end_date) and
            (role == "owner" or (role == "admin" and request.user.has_perm("rentals.change_rentalagreement"))),
        "can_download": agreement.status in ("scheduled", "active", "completed"),
        "detail_url": reverse(detail_name(role), args=[pk]),
    }
    if role in ("owner", "tenant"):
        from accounts.models import OwnerVerification, TenantIdentityAttempt
        # Badges describe actual identity approval, never inferred from agreement consent.
        context["owner_verified"] = OwnerVerification.objects.filter(user_id=agreement.owner_id, status="approved").exists()
        context["tenant_verified"] = TenantIdentityAttempt.objects.filter(user_id=agreement.tenant_id, status="approved").exists()
    if role == "tenant":
        from listings.services import tenant_readable_listings
        # Occupancy may block new requests without hiding an approved room from its tenant.
        context["can_view_room"] = tenant_readable_listings(request.user).filter(pk=agreement.listing_id).exists()
    template = {"owner": "accounts/owner_agreement_details.html", "admin": "custom_admin/agreement_details.html"}.get(role, "accounts/agreement_details.html")
    return render(request, template, context)


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def agreement_prepare(request, pk):
    response = request_access(request, True)
    if response:
        return response
    application = get_object_or_404(scoped_requests(request.user, True), pk=pk, status="accepted")
    agreement = RentalAgreement.objects.filter(rental_request=application).select_related("current_terms").first()
    if agreement and (agreement.workflow_version != 2 or agreement.status not in ("draft", "changes_requested")):
        return redirect("accounts:owner_agreement_details", pk=agreement.pk)
    names = ("monthly_rent", "security_deposit", "payment_due_day", "start_date", "end_date", "additional_terms")
    terms = agreement.current_terms if agreement else None
    initial = {name: getattr(terms, name) for name in names} if terms else {
        "monthly_rent": application.listing_revision.monthly_rent, "security_deposit": application.listing_revision.security_deposit,
        "start_date": max(local_today(), application.preferred_move_in, application.listing.published_revision.available_from),
    }
    form = AgreementTermsForm(request.POST if request.method == "POST" else None, initial=initial)
    form.fields["start_date"].widget.attrs["min"] = local_today().isoformat()
    if request.method == "POST" and form.is_valid():
        try:
            submitted_terms_id = request.POST.get("terms_id", "").strip()
            expected = int(submitted_terms_id) if submitted_terms_id else None
            agreement = prepare_agreement(request.user, application.pk, {name: form.cleaned_data[name] for name in names}, expected)
        except (ValueError, ValidationError) as error:
            form.add_error(None, error.messages if isinstance(error, ValidationError) else "Reload the agreement before saving.")
        except IntegrityError:
            form.add_error(None, "The agreement changed. Reload and try again.")
        else:
            messages.success(request, "Agreement terms saved. Review and send this version to the Tenant.")
            return redirect("accounts:owner_agreement_details", pk=agreement.pk)
    return render(request, "accounts/agreement_prepare.html", {"form": form, "application": application, "terms": terms,
        "expected_terms_id": request.POST.get("terms_id", "") if request.method == "POST" else (terms.pk if terms else "")})


@login_required(login_url="accounts:login")
@require_POST
def agreement_action(request, pk, action, role="tenant"):
    response = agreement_access(request, role)
    if response:
        return response
    agreement = get_object_or_404(scoped_agreements(request.user), pk=pk)
    reason_action = action in ("changes", "return")
    form = AgreementReasonForm(request.POST) if reason_action else AgreementActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Supply an explanation for this version." if reason_action else "Confirm consent for the displayed agreement version.")
    else:
        try:
            terms_id = form.cleaned_data["terms_id"]
            if action == "changes":
                request_agreement_changes(request.user, agreement.pk, terms_id, form.cleaned_data["reason"])
            elif action in ("approve", "return"):
                review_agreement(request.user, agreement.pk, terms_id, action, form.cleaned_data.get("reason", ""))
            else:
                {"send": send_agreement, "confirm": confirm_agreement, "finalize": finalize_agreement,
                    "complete": complete_agreement}[action](request.user, agreement.pk, terms_id)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        except IntegrityError:
            messages.error(request, "A conflicting agreement or state change prevented this action. Reload and review.")
        else:
            messages.success(request, "Agreement updated.")
    return redirect(detail_name(role), pk=pk)


@login_required(login_url="accounts:login")
@require_GET
def agreement_download(request, pk, role="tenant"):
    response = agreement_access(request, role)
    if response:
        return response
    agreement = get_object_or_404(scoped_agreements(request.user).select_related("current_terms"), pk=pk)
    if agreement.status not in ("scheduled", "active", "completed"):
        raise Http404
    # Render the binding immutable version only; no public media file or guessed path exists.
    response = render(request, "accounts/agreement_document.html", {"agreement": agreement, "terms": agreement.current_terms, "document_download": True})
    response["Content-Disposition"] = f'attachment; filename="agreement-{agreement.pk}.html"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
