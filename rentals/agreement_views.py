from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.admin_dashboard_views import require_staff
from .agreement_services import (complete_agreement, confirm_agreement, finalize_agreement, local_today,
    prepare_agreement, scoped_agreements, send_agreement)
from .forms import AgreementActionForm, AgreementTermsForm
from .models import RentalAgreement
from .views import paginated_statuses, request_access, scoped_requests


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
    query = request.GET.get("q", "").strip()[:150] if role == "admin" else ""
    if query:
        condition = Q(current_terms__tenant_snapshot__full_name__icontains=query) | Q(current_terms__owner_snapshot__full_name__icontains=query)
        if query.isdecimal():
            condition |= Q(pk=int(query))
        records = records.filter(condition)
    context = paginated_statuses(request, records, RentalAgreement.Status.choices, per_page=3)
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
    context = {"agreement": agreement, "terms": terms, "role": role, "versions": versions,
        "current_version": current, "today": local_today(),
        "can_confirm": role == "tenant" and current and agreement.status == "pending" and terms.sent_at and not terms.tenant_accepted_at,
        "can_edit": role == "owner" and agreement.status == "pending" and current,
        "can_send": role == "owner" and agreement.status == "pending" and current and not terms.sent_at,
        "can_finalize": role == "owner" and agreement.status == "pending" and current and terms.tenant_accepted_at,
        "can_complete": current and agreement.status == "active" and local_today() >= terms.end_date and
            (role == "owner" or (role == "admin" and request.user.has_perm("rentals.change_rentalagreement"))),
        "detail_url": reverse(detail_name(role), args=[pk]),
    }
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
    if agreement and agreement.status != "pending":
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
    form = AgreementActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Confirm the action for the displayed agreement version.")
    else:
        try:
            {"send": send_agreement, "confirm": confirm_agreement, "finalize": finalize_agreement,
                "complete": complete_agreement}[action](request.user, agreement.pk, form.cleaned_data["terms_id"])
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
