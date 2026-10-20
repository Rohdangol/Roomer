from django import forms
from .models import OwnerVerification


class VerificationFilterForm(forms.Form):
    status = forms.ChoiceField(choices=[("all", "All"), *OwnerVerification.Status.choices], required=False)
    role = forms.ChoiceField(choices=[("all", "All roles"), ("tenant", "Tenant"), ("owner", "Owner")], required=False)
    q = forms.CharField(required=False, max_length=254, label="Search by name or email")


class IdentityDecisionForm(forms.Form):
    submitted_version = forms.CharField(widget=forms.HiddenInput)
    decision = forms.ChoiceField(choices=[("approved", "Approve"), ("rejected", "Reject")], widget=forms.RadioSelect)
    reason = forms.CharField(required=False, max_length=5000, label="Rejection reason",
        widget=forms.Textarea(attrs={"rows": 4}))
    confirm = forms.BooleanField(label="I confirm this identity review decision.")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "rejected" and not cleaned.get("reason"):
            self.add_error("reason", "A rejection reason is required.")
        return cleaned
