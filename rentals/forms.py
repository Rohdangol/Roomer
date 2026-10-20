from decimal import Decimal

from django import forms
from django.utils import timezone


class RentalRequestForm(forms.Form):
    preferred_move_in = forms.DateField(label="Preferred Move-in Date", widget=forms.DateInput(attrs={"type": "date"}))
    total_occupancy = forms.IntegerField(label="Total Occupancy (including you)", min_value=1, max_value=32767)
    message = forms.CharField(label="Message to Owner", widget=forms.Textarea(attrs={"rows": 4}))
    confirm = forms.BooleanField(label="I confirm that I want to send this rental request.")

    def __init__(self, *args, listing, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preferred_move_in"].widget.attrs["min"] = max(timezone.localdate(), listing.published_revision.available_from).isoformat()
        self.fields["total_occupancy"].widget.attrs["max"] = listing.published_revision.maximum_occupants


class ConfirmActionForm(forms.Form):
    confirm = forms.BooleanField(label="I confirm this action.")


class AgreementTermsForm(forms.Form):
    monthly_rent = forms.DecimalField(label="Monthly Rent", max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    security_deposit = forms.DecimalField(label="Security Deposit", max_digits=12, decimal_places=2, min_value=0)
    payment_due_day = forms.IntegerField(label="Payment Due Day", min_value=1, max_value=28)
    start_date = forms.DateField(label="Start Date", widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(label="End Date (exclusive)", widget=forms.DateInput(attrs={"type": "date"}))
    additional_terms = forms.CharField(label="Additional Terms & Conditions", widget=forms.Textarea(attrs={"rows": 6}))
    confirm = forms.BooleanField(label="I confirm these agreement terms.")


class AgreementActionForm(ConfirmActionForm):
    terms_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
