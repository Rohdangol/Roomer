from django import forms
from math import radians

from django.db.models import Exists, OuterRef, ExpressionWrapper, FloatField, Prefetch, Q, Value
from django.db.models.functions import ASin, Cast, Cos, Greatest, Least, Radians, Sin, Sqrt

from listings.choices import Furnishing, RoomType
from listings.models import Amenity, ListingAmenity
from listings.services import published_listings


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
        # Haversine stays in SQL so nearby filtering happens before counting/pagination.
        latitude = radians(filters["latitude"])
        longitude = radians(filters["longitude"])
        room_lat = Radians(Cast("published_revision__latitude", FloatField()))
        room_lon = Radians(Cast("published_revision__longitude", FloatField()))
        half_chord = Sin((room_lat - latitude) / 2.0) ** 2.0 + Cos(Value(latitude)) * Cos(room_lat) * Sin((room_lon - longitude) / 2.0) ** 2.0
        distance = ExpressionWrapper(12742.0 * ASin(Sqrt(Least(Value(1.0), Greatest(Value(0.0), half_chord)))), output_field=FloatField())
        rooms = rooms.filter(published_revision__latitude__isnull=False, published_revision__longitude__isnull=False).annotate(distance_km=distance).filter(distance_km__lte=filters.get("radius") or 2)
    query = filters.get("q")
    if query:
        rooms = rooms.filter(Q(published_revision__city__icontains=query) | Q(published_revision__locality__icontains=query) | Q(published_revision__address__icontains=query))
    area = filters.get("area")
    if area:
        # Listings without a mapped area remain discoverable by their city/address.
        rooms = rooms.filter(Q(published_revision__locality=area) | (
            Q(published_revision__locality="") & (
                Q(published_revision__city__icontains=area) | Q(published_revision__address__icontains=area))))
    for field in ("city", "room_type", "furnishing"):
        value = filters.get(field)
        if value:
            rooms = rooms.filter(**{f"published_revision__{field}": value})
    if filters.get("max_budget") is not None:
        rooms = rooms.filter(published_revision__monthly_rent__lte=filters["max_budget"])
    # Each selected amenity is required, not merely any one of the selections.
    for amenity in filters.get("amenities", []):
        rooms = rooms.filter(published_revision__amenity_links__amenity=amenity)
    return rooms.order_by("-published_at", "-pk").prefetch_related(
        "published_revision__photos",
        Prefetch("published_revision__amenity_links", queryset=ListingAmenity.objects.select_related("amenity")),
    )
