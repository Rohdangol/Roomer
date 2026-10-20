from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import CharField, Q, Value
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from .admin_dashboard_views import can_view, require_staff
from .admin_verification_forms import IdentityDecisionForm, VerificationFilterForm
from .models import OwnerVerification, TenantIdentityAttempt, TenantIdentityReview
from .verification_services import email_is_verified, review_owner_identity, review_tenant_identity


IDENTITY_MODELS = {"owner": OwnerVerification, "tenant": TenantIdentityAttempt}


def identity_model(request, role):
    require_staff(request.user)
    model = IDENTITY_MODELS.get(role)
    if model is None:
        raise Http404
    if not can_view(request, model):
        raise PermissionDenied("Identity submission permission is required.")
    return model


@login_required(login_url="accounts:login")
@require_GET
def submissions(request):
    require_staff(request.user)
    allowed = [(role, model) for role, model in IDENTITY_MODELS.items() if can_view(request, model)]
    if not allowed:
        raise PermissionDenied("Identity submission permission is required.")
    parameters = request.GET.copy()
    parameters.setdefault("status", "all")
    parameters.setdefault("role", "all")
    form = VerificationFilterForm(parameters)
    records = []
    if form.is_valid():
        queries = []
        for role, model in allowed:
            if form.cleaned_data["role"] not in ("", "all", role):
                continue
            rows = model.objects.all()
            status, query = form.cleaned_data["status"], form.cleaned_data["q"]
            if status and status != "all":
                rows = rows.filter(status=status)
            if query:
                rows = rows.filter(Q(user__full_name__icontains=query) | Q(user__email__icontains=query))
            queries.append(rows.order_by().annotate(applicant_role=Value(role, output_field=CharField()))
                .values("pk", "user__full_name", "user__email", "submitted_at", "status", "applicant_role"))
        if queries:
            records = queries[0].union(*queries[1:]) if len(queries) > 1 else queries[0]
            records = records.order_by("-submitted_at", "-pk", "applicant_role")
    page = Paginator(records, 6).get_page(request.GET.get("page"))
    for row in page:
        row["review_url"] = reverse("accounts:admin_verification_review", args=[row["applicant_role"], row["pk"]])
        row["status_label"] = dict(OwnerVerification.Status.choices).get(row["status"], "Unavailable")
    parameters.pop("page", None)
    return render(request, "custom_admin/verifications.html", {"form": form, "page_obj": page,
        "pagination_query": parameters.urlencode(), "page_numbers": page.paginator.get_elided_page_range(page.number),
        "status": parameters.get("status", "all"), "role": parameters.get("role", "all"), "query": parameters.get("q", ""),
        "status_filters": [("all", "All"), ("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]})


@login_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def review(request, role, pk):
    model = identity_model(request, role)
    submission = get_object_or_404(model.objects.select_related("user", "reviewed_by"), pk=pk)
    can_decide = request.user.has_perm(f"accounts.change_{model._meta.model_name}") and submission.user_id != request.user.pk
    if request.method == "POST" and not can_decide:
        raise PermissionDenied("Identity change permission is required; self review is not allowed.")
    form = IdentityDecisionForm(request.POST if request.method == "POST" else None,
        initial={"submitted_version": submission.submitted_at.isoformat()})
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                if role == "owner":
                    reviewed = review_owner_identity(request.user, pk, form.cleaned_data["decision"],
                        form.cleaned_data["reason"], form.cleaned_data["submitted_version"])
                    outcome = "applied"
                else:
                    # Tenant attempts never replace documents; the service locks and audits every decision.
                    if form.cleaned_data["submitted_version"] != submission.submitted_at.isoformat():
                        raise ValidationError("Submission version changed. Reload before reviewing.")
                    outcome = review_tenant_identity(request.user, pk, form.cleaned_data["decision"], form.cleaned_data["reason"])
                    reviewed = submission
                if outcome == "applied":
                    admin.site._registry[model].log_change(request, reviewed,
                        f"Identity {form.cleaned_data['decision']} through custom review. " +
                        ("Reason: " + form.cleaned_data["reason"] if form.cleaned_data["decision"] == "rejected" else ""))
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            if outcome == "applied":
                messages.success(request, "Identity review saved. Email verification is unchanged.")
            else:
                messages.warning(request, "Decision not applied: this attempt was already reviewed or the decision was invalid.")
            return redirect("accounts:admin_verification_review", role=role, pk=pk)
    submission.refresh_from_db()
    documents = []
    if role == "owner":
        documents.append({"label": "Identity document", "url": reverse("accounts:verification_document", args=[pk]),
            "preview": submission.document.name.lower().endswith((".jpg", ".jpeg", ".png"))})
    else:
        for side in ("front", "back"):
            documents.append({"label": side.title() + " document", "url": reverse("accounts:tenant_identity_document", args=[pk, side]), "preview": True})
    history = []
    if role == "tenant" and can_view(request, TenantIdentityReview):
        history = submission.reviews.select_related("reviewer").order_by("-created_at", "-pk")
    owner_history = []
    if role == "owner":
        owner_history = LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(model),
            object_id=str(pk)).select_related("user").order_by("-action_time", "-pk")
    return render(request, "custom_admin/verification_review.html", {"submission": submission,
        "role": role, "form": form, "can_decide": can_decide, "documents": documents,
        "email_verified": email_is_verified(submission.user), "review_history": history,
        "can_history": role == "owner" or can_view(request, TenantIdentityReview), "owner_history": owner_history,
        "attempt_history": TenantIdentityAttempt.objects.filter(user=submission.user).order_by("-submitted_at", "-pk") if role == "tenant" else [],
    })
