from django import forms
from django.utils import timezone
from listings.models import Amenity, ListingRevision
from listings.services import DRAFT_FIELDS, validate_available_from
from listings.storage import validate_photo


class MultiplePhotoInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class ListingPhotosField(forms.FileField):
    widget = MultiplePhotoInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else ([data] if data else [])
        if not files and not self.required:
            return []
        if not 1 <= len(files) <= 10:
            raise forms.ValidationError("Upload between 1 and 10 photos.")
        for photo in files:
            super().clean(photo)
            validate_photo(photo)
        return files


class OwnerListingForm(forms.ModelForm):
    amenities = forms.ModelMultipleChoiceField(queryset=Amenity.objects.all(), required=False,
        widget=forms.CheckboxSelectMultiple)
    photos = ListingPhotosField(label="Room photos", widget=MultiplePhotoInput(attrs={
        "accept": ".jpg,.jpeg,.png,.webp", "aria-describedby": "photo-help"}))

    class Meta:
        model = ListingRevision
        # Owner, status and approval fields are never accepted from the browser.
        fields = DRAFT_FIELDS
        widgets = {
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
            "available_from": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "quiet_hours_start": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "quiet_hours_end": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "description": forms.Textarea(attrs={"rows": 5}),
            "additional_rules": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {"bathroom_details": "Bathroom", "maximum_occupants": "Maximum occupancy",
            "available_from": "Available from (AD)", "monthly_rent": "Monthly rent (NPR)",
            "security_deposit": "Security deposit (NPR)", "quiet_hours_start": "Quiet hours from (optional)",
            "quiet_hours_end": "Quiet hours to (optional)"}

    def __init__(self, *args, source=None, **kwargs):
        self.source = source
        super().__init__(*args, **kwargs)
        previous = source
        if source is not None and source.approval_status == "draft":
            previous = source.listing.revisions.exclude(approval_status="draft").order_by("-version").first()
        self.previous_available_from = previous.available_from if previous else None
        today = timezone.localdate()
        minimum = min(today, self.previous_available_from) if self.previous_available_from else today
        self.fields["available_from"].widget.attrs.update({
            "min": minimum.isoformat(), "data-today": today.isoformat(),
            "data-original-date": self.previous_available_from.isoformat() if self.previous_available_from else "",
        })
        # Bathroom is no longer editable; retain its snapshot value when submitting edits.
        self.fields["bathroom_details"].disabled = True
        # New submissions and edits need an explicit neighbourhood; legacy rows stay intact.
        self.fields["locality"].required = True
        self.fields["locality"].label = "Locality / Neighbourhood"
        self.fields["locality"].widget.attrs["placeholder"] = "e.g. Baneshwor"
        self.fields["locality"].help_text = "Used in Browse by Neighbourhood after approval."
        if source is not None:
            self.fields["photos"].required = False
            self.fields["remove_photos"] = forms.ModelMultipleChoiceField(
                queryset=source.photos.all(), required=False, widget=forms.CheckboxSelectMultiple)
            self.fields["source_version"] = forms.CharField(widget=forms.HiddenInput,
                initial=f"{source.pk}:{source.updated_at.isoformat()}")
            self.initial["amenities"] = list(source.amenity_links.values_list("amenity_id", flat=True))
        for name in ("cooking_allowed", "visitors_allowed", "smoking_allowed", "pets_allowed"):
            self.fields[name] = forms.TypedChoiceField(label=self.fields[name].label,
                choices=(("True", "Yes"), ("False", "No")), coerce=lambda value: value == "True",
                widget=forms.RadioSelect)
        for name, minimum, maximum in (("latitude", -90, 90), ("longitude", -180, 180)):
            self.fields[name].min_value = minimum
            self.fields[name].max_value = maximum
            self.fields[name].widget.attrs.update(min=minimum, max=maximum, step="0.000001")
        for name, minimum in (("monthly_rent", "0.01"), ("security_deposit", "0"), ("maximum_occupants", "1")):
            self.fields[name].widget.attrs["min"] = minimum

    def clean(self):
        cleaned = super().clean()
        try:
            validate_available_from(cleaned.get("available_from"), self.previous_available_from)
        except forms.ValidationError as error:
            self.add_error("available_from", error.error_dict["available_from"])
        for name, minimum, maximum in (("latitude", -90, 90), ("longitude", -180, 180)):
            if cleaned.get(name) is not None and not minimum <= cleaned[name] <= maximum:
                self.add_error(name, "Select a valid location on the map.")
        start, end = cleaned.get("quiet_hours_start"), cleaned.get("quiet_hours_end")
        if (start is None) != (end is None):
            self.add_error("quiet_hours_end", "Provide both quiet-hour times or leave both empty.")
        for name in ("monthly_rent", "maximum_occupants"):
            if cleaned.get(name) is not None and cleaned[name] <= 0:
                self.add_error(name, "Enter a value greater than zero.")
        if cleaned.get("security_deposit") is not None and cleaned["security_deposit"] < 0:
            self.add_error("security_deposit", "Enter zero or a positive amount.")
        if self.source is not None:
            remaining = self.source.photos.count() - len(cleaned.get("remove_photos", []))
            if not 1 <= remaining + len(cleaned.get("photos", [])) <= 10:
                self.add_error("photos", "Keep or upload between 1 and 10 photos in total.")
        return cleaned


def listing_form_sections(form):
    sections = [
        ("Basic Information", ("title", "room_type", "furnishing", "floor", "maximum_occupants")),
        ("Location", ("city", "locality", "address", "latitude", "longitude")),
        ("Pricing & Availability", ("monthly_rent", "security_deposit", "available_from")),
        ("Amenities", ("amenities",)), ("About this Room", ("description",)),
        ("House Rules", ("cooking_allowed", "visitors_allowed", "smoking_allowed", "pets_allowed",
            "quiet_hours_start", "quiet_hours_end", "additional_rules")),
    ]
    return [(title, [form[name] for name in fields]) for title, fields in sections]
