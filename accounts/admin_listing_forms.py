from django import forms
from .models import User


class AdminListingFilterForm(forms.Form):
    status = forms.ChoiceField(choices=[("all", "All"), ("available", "Available"),
        ("reserved", "Reserved"), ("occupied", "Occupied"), ("inactive", "Inactive")], required=False)
    q = forms.CharField(required=False, max_length=254, label="Search by title, location or owner",
        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Search by title, location or owner"}))
    # Validate the target owner rather than silently broadening an invalid owner filter.
    owner = forms.ModelChoiceField(queryset=User.objects.filter(role=User.Role.OWNER),
        required=False, widget=forms.HiddenInput)


class ListingDecisionForm(forms.Form):
    revision_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    submitted_version = forms.CharField(widget=forms.HiddenInput)
    decision = forms.ChoiceField(choices=[("approved", "Approve"), ("rejected", "Reject")], widget=forms.RadioSelect)
    reason = forms.CharField(required=False, max_length=5000, label="Rejection reason",
        widget=forms.Textarea(attrs={"rows": 4}))
    confirm = forms.BooleanField(label="I confirm this listing review decision.")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "rejected" and not cleaned.get("reason"):
            self.add_error("reason", "A rejection reason is required.")
        return cleaned
