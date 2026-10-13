from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404

from listings.models import RoomListing
from listings.services import published_listings
from .models import SavedRoom


def require_tenant(actor):
    if not actor.is_authenticated or not actor.is_active or actor.is_staff or actor.role != "tenant":
        raise PermissionDenied("An active tenant account is required.")


@transaction.atomic
def save_room(actor, listing_id):
    require_tenant(actor)
    # Lock the stable listing; explicit save is idempotent, including double submissions.
    get_object_or_404(RoomListing.objects.select_for_update(), pk=listing_id)
    get_object_or_404(published_listings(), pk=listing_id)
    return SavedRoom.objects.get_or_create(tenant=actor, listing_id=listing_id)[1]


def remove_saved_room(actor, listing_id):
    require_tenant(actor)
    # Removal stays available when the listing is no longer publicly eligible.
    return SavedRoom.objects.filter(tenant=actor, listing_id=listing_id).delete()[0] > 0
