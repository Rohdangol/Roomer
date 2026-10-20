from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from listings.services import require_owner
from .permissions import owner_needs_verification
from rentals.views import request_list


@login_required(login_url="accounts:login")
@require_GET
def rental_requests(request):
    return request_list(request, owner=True)


@login_required(login_url="accounts:login")
@require_GET
def request_details_layout(request):
    require_owner(request.user)
    if owner_needs_verification(request.user):
        return redirect("accounts:verification")
    # Legacy layout bookmarks lead to the scoped list; details require a real record ID.
    return redirect("accounts:owner_requests")
