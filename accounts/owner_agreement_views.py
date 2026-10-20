from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from listings.services import require_owner
from .permissions import owner_needs_verification
from rentals.agreement_views import agreement_list


@login_required(login_url="accounts:login")
@require_GET
def my_agreements(request):
    return agreement_list(request, role="owner")


@login_required(login_url="accounts:login")
@require_GET
def agreement_details_layout(request):
    require_owner(request.user)
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    # Legacy layout bookmarks lead to the scoped list; details require a real record ID.
    return redirect("accounts:owner_agreements")
