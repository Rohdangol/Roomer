from uuid import uuid4

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import RegexValidator

from .models import OwnerVerification, User


class OwnerVerificationForm(forms.ModelForm):
    class Meta:
        model = OwnerVerification
        fields = ("document_type", "document")
        labels = {"document_type": "Identity document", "document": "Document upload"}
        help_texts = {"document": "Upload a clear JPG, PNG, or PDF, up to 5 MB."}


class EmailLoginForm(forms.Form):
    email = forms.EmailField(label="Email Address")
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user_cache = None

    def clean(self):
        cleaned_data = super().clean()
        self.user_cache = None
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")
        if email and password:
            email = User.objects.normalize_email(email)
            cleaned_data["email"] = email
            self.user_cache = authenticate(self.request, email=email, password=password)
            if self.user_cache is None:
                raise forms.ValidationError("Invalid email or password.", code="invalid_login")
        return cleaned_data

    def get_user(self):
        return self.user_cache


class RegistrationForm(UserCreationForm):
    full_name = forms.CharField(max_length=150, label="Full Name")
    phone_number = forms.CharField(
        max_length=20,
        label="Phone Number",
        validators=[RegexValidator(
            regex=r"\A\+?[0-9]{7,15}\Z",
            message="Enter 7–15 digits, optionally starting with +.",
        )],
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("full_name", "email", "phone_number", "role", "password1", "password2")
        labels = {"email": "Email Address", "role": "I am a"}
        widgets = {"role": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password2"].label = "Confirm Password"
        self.fields["full_name"].widget.attrs["autocomplete"] = "name"
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["phone_number"].widget.attrs.update(autocomplete="tel", inputmode="tel")

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def save(self, commit=True):
        # Django hashes the password even when the caller saves the user later.
        user = super().save(commit=False)
        if not user.username:
            username = uuid4().hex
            while User.objects.filter(username=username).exists():
                username = uuid4().hex
            user.username = username
        # Public registration must never grant Django admin permissions.
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
            self.save_m2m()
        return user
