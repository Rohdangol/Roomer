from django import forms
from django.core.validators import RegexValidator

from listings.models import Amenity
from listings.choices import Furnishing
from preferences.models import TenantPreference
from .models import User


class PersonalInformationForm(forms.ModelForm):
    full_name = forms.CharField(max_length=150, label="Full Name")
    phone_number = forms.CharField(max_length=20, label="Phone Number", validators=[RegexValidator(r"\A\+?[0-9]{7,15}\Z", "Enter 7-15 digits, optionally starting with +.")])

    class Meta:
        model = User
        # Email is read-only by agreement; permissions and internal identity are excluded.
        fields = ("full_name", "phone_number")


class ProfilePictureForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("profile_picture",)
        widgets = {"profile_picture": forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"})}
        help_texts = {"profile_picture": "JPEG, PNG or WebP; up to 5 MB. Animated images are not accepted."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile_picture"].required = True


    def clean_profile_picture(self):
        if not self.files.get("profile_picture"):
            raise forms.ValidationError("Choose a new profile picture to upload.")
        return self.cleaned_data["profile_picture"]


class RoomPreferenceForm(forms.ModelForm):
    coordinates_selected = forms.BooleanField(required=False, widget=forms.HiddenInput)
    preferred_furnishing = forms.ChoiceField(choices=[("any", "Any"), *Furnishing.choices], required=False, initial="any", label="Furnishing")
    amenities = forms.ModelMultipleChoiceField(queryset=Amenity.objects.all(), required=False, widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = TenantPreference
        fields = ("preferred_location", "latitude", "longitude", "preferred_room_type", "maximum_budget", "preferred_furnishing", "amenities", "coordinates_selected")
        labels = {"preferred_location": "Preferred Location", "preferred_room_type": "Room Type", "maximum_budget": "Maximum Monthly Budget (NPR)", "preferred_furnishing": "Furnishing"}
        help_texts = {"preferred_location": "Enter the area name. Map coordinates are optional; provide both or leave both empty."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["latitude"].min_value = -90
        self.fields["longitude"].min_value = -180
        self.fields["latitude"].widget.attrs.update(min=-90, max=90, step="0.000001")
        self.fields["longitude"].widget.attrs.update(min=-180, max=180, step="0.000001")
        self.fields["maximum_budget"].widget.attrs.update(min="0.01", step="0.01")
        if self.instance.pk:
            self.initial["amenities"] = list(self.instance.amenity_links.values_list("amenity_id", flat=True))

    def clean(self):
        cleaned = super().clean()
        cleaned.setdefault("latitude", None)
        cleaned.setdefault("longitude", None)
        if (cleaned["latitude"] is None) != (cleaned["longitude"] is None):
            raise forms.ValidationError("Provide both coordinates or leave both empty.")
        return cleaned

    def clean_preferred_furnishing(self):
        return self.cleaned_data.get("preferred_furnishing") or "any"

    def clean_latitude(self):
        value = self.cleaned_data["latitude"]
        if value is not None and not -90 <= value <= 90:
            raise forms.ValidationError("Latitude must be between -90 and 90.")
        return value

    def clean_longitude(self):
        value = self.cleaned_data["longitude"]
        if value is not None and not -180 <= value <= 180:
            raise forms.ValidationError("Longitude must be between -180 and 180.")
        return value

    def clean_maximum_budget(self):
        value = self.cleaned_data["maximum_budget"]
        if value <= 0:
            raise forms.ValidationError("Enter a budget greater than zero.")
        return value


class TextOnlyPreferenceForm(RoomPreferenceForm):
    point_location = forms.CharField(required=False, widget=forms.HiddenInput)
    resolved_label = forms.CharField(required=False, widget=forms.HiddenInput)
    location_token = forms.CharField(required=False, widget=forms.HiddenInput)
    point_source = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved_location = self.instance.preferred_location.strip()
        self.saved_coordinates = (self.instance.latitude, self.instance.longitude)
        from .search_location import signed_place
        # Coordinates are selection metadata, never visible numeric inputs.
        for name in ("latitude", "longitude", "coordinates_selected"):
            self.fields[name].widget = forms.HiddenInput()
        if not self.is_bound and self.instance.latitude is not None and self.instance.longitude is not None:
            self.initial.update(signed_place({"label": self.instance.preferred_location,
                "latitude": self.instance.latitude, "longitude": self.instance.longitude}))
        self.fields["preferred_location"].help_text = "Choose a suggestion to save a map point for recommendations."

    def clean(self):
        cleaned = super().clean()
        from .search_location import selected_location
        selected = selected_location({**cleaned, "q": cleaned.get("preferred_location", "")})
        changed = cleaned.get("preferred_location", "").strip() != self.saved_location
        if changed and not selected:
            self.add_error("preferred_location", "Choose a location from the suggestions before saving a changed location.")
        elif not selected and not changed and all(value is not None for value in self.saved_coordinates):
            # Editing other preferences must not erase an unchanged saved point,
            # including submissions without JavaScript selection metadata.
            cleaned["latitude"], cleaned["longitude"] = self.saved_coordinates
        elif cleaned.get("latitude") is not None and not selected:
            self.add_error("preferred_location", "Choose a location from the suggestions.")
        cleaned["coordinates_selected"] = selected
        return cleaned


class TenantIdentityForm(forms.ModelForm):
    class Meta:
        from .models import TenantIdentityAttempt
        model = TenantIdentityAttempt
        fields = ("document_type", "document_number", "issued_date", "front_document", "back_document")
        widgets = {"document_type": forms.RadioSelect, "issued_date": forms.DateInput(attrs={"type": "date"}), "front_document": forms.FileInput(attrs={"accept": "image/jpeg,image/png"}), "back_document": forms.FileInput(attrs={"accept": "image/jpeg,image/png"})}
        labels = {"issued_date": "Issued Date (AD / Gregorian)", "document_number": "Document Identification Number", "front_document": "Front Side", "back_document": "Back Side"}

    def clean_issued_date(self):
        from zoneinfo import ZoneInfo
        from django.utils import timezone
        date = self.cleaned_data["issued_date"]
        if date > timezone.localdate(timezone=ZoneInfo("Asia/Kathmandu")):
            raise forms.ValidationError("Issued date must be a past or current AD date; BS dates are not converted.")
        return date
