from django import forms

from django.db.models import Exists, OuterRef, Prefetch, Q
from listings.distance import rooms_within_radius

from listings.choices import Furnishing, RoomType
from listings.models import Amenity, ListingAmenity
from listings.services import published_listings
from .neighbourhoods import location_pattern, normalized_location


class RoomSearchForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sidebar widgets belong to the detached GET form, outside the POST card forms.
        for field in self.fields.values():
            field.widget.attrs["form"] = "room-search"

    q = forms.CharField(required=False, max_length=255, label="Location", widget=forms.TextInput(attrs={"placeholder": "City, neighbourhood or address"}))
    area = forms.CharField(required=False, max_length=100, widget=forms.HiddenInput)
    city = forms.CharField(required=False, max_length=100, widget=forms.HiddenInput)
    latitude = forms.FloatField(required=False, min_value=-90, max_value=90, widget=forms.HiddenInput)
    longitude = forms.FloatField(required=False, min_value=-180, max_value=180, widget=forms.HiddenInput)
    point_location = forms.CharField(required=False, max_length=255, widget=forms.HiddenInput)
    resolved_label = forms.CharField(required=False, max_length=1000, widget=forms.HiddenInput)
    location_token = forms.CharField(required=False, max_length=2500, widget=forms.HiddenInput)
    point_source = forms.ChoiceField(required=False, choices=[("suggestion", "Suggestion"), ("map", "Map"), ("gps", "GPS")], widget=forms.HiddenInput)
    radius = forms.TypedChoiceField(required=False, coerce=int, empty_value=2, choices=[(1, "1 km"), (2, "2 km"), (5, "5 km")], label="Nearby radius", initial=2)
    max_budget = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2, label="Maximum monthly budget (NPR)")
    room_type = forms.ChoiceField(required=False, choices=[("", "Any room type"), *RoomType.choices], label="Room Type", widget=forms.RadioSelect)
    furnishing = forms.ChoiceField(required=False, choices=[("", "Any furnishing"), *Furnishing.choices], label="Furnishing", widget=forms.RadioSelect)
    amenities = forms.ModelMultipleChoiceField(required=False, queryset=Amenity.objects.all(), widget=forms.CheckboxSelectMultiple)


    def clean(self):
        cleaned = super().clean()
        if (cleaned.get("latitude") is None) != (cleaned.get("longitude") is None):
            raise forms.ValidationError("Select both latitude and longitude for nearby search.")
        return cleaned


def search_rooms(filters, tenant=None):
    """Shared Home/Find Rooms query: always read eligible approved snapshots."""
    rooms = published_listings()
    if tenant is not None:
        from saved_rooms.models import SavedRoom
        rooms = rooms.annotate(is_saved=Exists(SavedRoom.objects.filter(tenant=tenant, listing_id=OuterRef("pk"))))
    if filters.get("latitude") is not None and filters.get("longitude") is not None:
        rooms = rooms_within_radius(rooms, filters["latitude"], filters["longitude"], filters.get("radius") or 2)
    query = filters.get("q")
    has_point = filters.get("latitude") is not None and filters.get("longitude") is not None
    if query and not has_point and not (filters.get("area") and normalized_location(query) == normalized_location(filters["area"])):
        rooms = rooms.filter(Q(published_revision__city__icontains=query) | Q(published_revision__locality__icontains=query) | Q(published_revision__address__icontains=query))
    area = filters.get("area")
    if area and not has_point:
        # Listings without a mapped area remain discoverable by their city/address.
        rooms = rooms.filter(Q(published_revision__locality__iregex=location_pattern(area)) | (
            Q(published_revision__locality="") & (
                Q(published_revision__city__icontains=area) | Q(published_revision__address__icontains=area))))
    for field in ("city", "room_type", "furnishing"):
        value = filters.get(field)
        if field == "city" and has_point:
            continue
        if value:
            lookup = "city__iregex" if field == "city" else field
            rooms = rooms.filter(**{f"published_revision__{lookup}": location_pattern(value) if field == "city" else value})
    if filters.get("max_budget") is not None:
        rooms = rooms.filter(published_revision__monthly_rent__lte=filters["max_budget"])
    # Each selected amenity is required, not merely any one of the selections.
    for amenity in filters.get("amenities", []):
        rooms = rooms.filter(published_revision__amenity_links__amenity=amenity)
    return rooms.order_by("-published_at", "-pk").prefetch_related(
        "published_revision__photos",
        Prefetch("published_revision__amenity_links", queryset=ListingAmenity.objects.select_related("amenity")),
    )
