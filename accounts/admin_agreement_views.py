from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from .admin_dashboard_views import require_staff
from rentals.agreement_views import agreement_list


@login_required(login_url="accounts:login")
@require_GET
def agreements(request):
    return agreement_list(request, role="admin")


@login_required(login_url="accounts:login")
@require_GET
def agreement_details_layout(request):
    require_staff(request.user)
    # Legacy layout bookmarks lead to the permission-checked list.
    return redirect("accounts:admin_agreements")
