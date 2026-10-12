from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import User
from .forms import RegistrationForm


class UserTests(TestCase):
    def test_manager_normalizes_email_and_preserves_phone_text(self):
        user = User.objects.create_user(
            username="tenant", email="  Tenant@EXAMPLE.COM  ",
            password="test-password", full_name="Test Tenant",
            phone_number="+977 0012345678",
        )
        user.refresh_from_db()
        self.assertEqual(user.email, "tenant@example.com")
        self.assertEqual(user.phone_number, "+977 0012345678")
        self.assertEqual(user.full_name, "Test Tenant")
        self.assertTrue(user.check_password("test-password"))
        self.assertEqual(user.role, User.Role.TENANT)

    def test_save_normalizes_email(self):
        user = User(username="direct", email="  Direct@EXAMPLE.COM  ")
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.email, "direct@example.com")
        user.email = "  Updated@EXAMPLE.COM "
        user.save(update_fields=["email"])
        user.refresh_from_db()
        self.assertEqual(user.email, "updated@example.com")

    def test_superuser_manager_keeps_username_and_permissions(self):
        user = User.objects.create_superuser(
            username="admin", email=" Admin@EXAMPLE.COM ", password="test-password",
        )
        self.assertEqual(user.email, "admin@example.com")
        self.assertEqual(User.USERNAME_FIELD, "username")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    def test_email_is_required_by_validation(self):
        with self.assertRaises(ValidationError) as error:
            User(username="missing", email="").full_clean()
        self.assertIn("email", error.exception.message_dict)

    def test_database_rejects_case_insensitive_duplicate_bypassing_save(self):
        User.objects.create_user(username="first", email="same@example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([
                User(username="second", email="SAME@EXAMPLE.COM"),
            ])

    def test_admin_includes_signup_fields(self):
        model_admin = admin.site._registry[User]
        for fieldsets in (model_admin.fieldsets, model_admin.add_fieldsets):
            fields = [field for title, options in fieldsets for field in options["fields"]]
            for field in ("email", "full_name", "phone_number", "role"):
                self.assertIn(field, fields)


class RegistrationFormTests(TestCase):
    def registration_data(self, **changes):
        data = {
            "full_name": "  Sample Person  ",
            "email": "  Person@EXAMPLE.COM  ",
            "phone_number": "  +9770123456789  ",
            "role": "tenant",
            "password1": "R3nt!River-Cloud#82",
            "password2": "R3nt!River-Cloud#82",
        }
        data.update(changes)
        return data

    def test_public_fields_order_and_required(self):
        form = RegistrationForm()
        fields = ["full_name", "email", "phone_number", "role", "password1", "password2"]
        self.assertEqual(list(form.fields), fields)
        for field in fields:
            with self.subTest(field=field):
                self.assertTrue(form.fields[field].required)
                form = RegistrationForm(self.registration_data(**{field: ""}))
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_successful_tenant_and_owner_registration(self):
        for role in ("tenant", "owner"):
            with self.subTest(role=role):
                form = RegistrationForm(self.registration_data(role=role, email=f"  {role}@EXAMPLE.COM  "))
                self.assertTrue(form.is_valid(), form.errors)
                user = form.save()
                user.refresh_from_db()
                self.assertEqual(user.role, role)
                self.assertEqual(user.full_name, "Sample Person")
                self.assertEqual(user.email, f"{role}@example.com")
                self.assertEqual(user.phone_number, "+9770123456789")
                self.assertNotEqual(user.password, form.cleaned_data["password1"])
                self.assertTrue(user.check_password(form.cleaned_data["password1"]))

    def test_case_insensitive_duplicate_email(self):
        User.objects.create_user(username="existing", email="person@example.com")
        form = RegistrationForm(self.registration_data())
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["email"], ["An account with this email address already exists."])

    def test_invalid_roles(self):
        for role in ("admin", "superuser", "Tenant"):
            with self.subTest(role=role):
                form = RegistrationForm(self.registration_data(role=role))
                self.assertFalse(form.is_valid())
                self.assertIn("role", form.errors)

    def test_invalid_phone_numbers(self):
        for phone in ("123456", "1234567890123456", "12 345678", "12-345678", "++1234567", "1234567+", "abcdefghi", "１２３４５６７"):
            with self.subTest(phone=phone):
                form = RegistrationForm(self.registration_data(phone_number=phone))
                self.assertFalse(form.is_valid())
                self.assertIn("phone_number", form.errors)

    def test_phone_boundaries_and_shared_phone(self):
        for index, phone in enumerate(("0123456", "+123456789012345", "0123456")):
            form = RegistrationForm(self.registration_data(email=f"person{index}@example.com", phone_number=phone))
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.save().phone_number, phone)

    def test_password_mismatch(self):
        form = RegistrationForm(self.registration_data(password2="Different!Password82"))
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_configured_password_validators(self):
        for password in ("x7!", "password", "93847561029384", "person@example.com"):
            with self.subTest(password=password):
                form = RegistrationForm(self.registration_data(password1=password, password2=password))
                self.assertFalse(form.is_valid())
                self.assertIn("password2", form.errors)

    def test_commit_false_returns_unsaved_user_with_hashed_password(self):
        form = RegistrationForm(self.registration_data())
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save(commit=False)
        self.assertIsNone(user.pk)
        self.assertEqual(User.objects.count(), 0)
        self.assertTrue(user.check_password(form.cleaned_data["password1"]))
        self.assertNotEqual(user.password, form.cleaned_data["password1"])
        self.assertTrue(user.username)
        user.save()
        self.assertEqual(User.objects.count(), 1)

    def test_internal_usernames_are_unique_and_fit_field(self):
        usernames = []
        for index in range(2):
            form = RegistrationForm(self.registration_data(email=f"person{index}@example.com"))
            self.assertTrue(form.is_valid(), form.errors)
            user = form.save()
            usernames.append(user.username)
            self.assertLessEqual(len(user.username), User._meta.get_field("username").max_length)
        self.assertEqual(len(set(usernames)), 2)

    def test_submitted_permissions_and_username_are_ignored(self):
        for commit in (False, True):
            with self.subTest(commit=commit):
                form = RegistrationForm(self.registration_data(
                    email=f"person{commit}@example.com", is_staff="true",
                    is_superuser="true", username="chosen-admin", groups=["1"],
                    user_permissions=["1"],
                ))
                self.assertTrue(form.is_valid(), form.errors)
                user = form.save(commit=commit)
                self.assertFalse(user.is_staff)
                self.assertFalse(user.is_superuser)
                self.assertNotEqual(user.username, "chosen-admin")
                if commit:
                    self.assertFalse(user.groups.exists())
                    self.assertFalse(user.user_permissions.exists())


class RegistrationViewTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:register")
        self.data = {
            "full_name": "Sample Person", "email": "person@example.com",
            "phone_number": "+9770123456789", "role": "tenant",
            "password1": "R3nt!River-Cloud#82", "password2": "R3nt!River-Cloud#82",
        }

    def test_get_displays_empty_form_and_local_stylesheet(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")
        self.assertFalse(response.context["form"].is_bound)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "/static/accounts/register.css")
        self.assertContains(response, reverse("accounts:login"))
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_post_preserves_values_but_not_passwords(self):
        self.data["password2"] = "different"
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("password2", response.context["form"].errors)
        for value in ("Sample Person", "person@example.com", "+9770123456789"):
            self.assertContains(response, value)
        self.assertNotContains(response, self.data["password1"])
        self.assertContains(response, 'id="id_password2_error"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertEqual(User.objects.count(), 0)

    def test_successful_roles_redirect_message_and_no_login(self):
        for role in ("tenant", "owner"):
            with self.subTest(role=role):
                self.data.update(role=role, email=f"{role}@example.com", is_staff="true", is_superuser="true")
                response = self.client.post(self.url, self.data, follow=True)
                self.assertRedirects(response, reverse("accounts:login"))
                self.assertContains(response, "Account created successfully. Please sign in.")
                self.assertFalse(response.context["form"].is_bound)
                user = User.objects.get(email=self.data["email"])
                self.assertEqual(user.role, role)
                self.assertFalse(user.is_staff)
                self.assertFalse(user.is_superuser)
                self.assertTrue(user.check_password(self.data["password1"]))
                self.assertNotIn("_auth_user_id", self.client.session)

    def test_existing_duplicate_email_shows_field_error(self):
        User.objects.create_user(username="existing", email="person@example.com")
        self.data["email"] = "PERSON@EXAMPLE.COM"
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An account with this email address already exists.")
        self.assertIn("email", response.context["form"].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_concurrent_duplicate_rolls_back_and_shows_email_error(self):
        original_is_valid = RegistrationForm.is_valid

        def validate_then_competing_signup(form):
            valid = original_is_valid(form)
            if valid:
                # Simulate another signup committing after this form's validation.
                User.objects.create_user(username="competing", email=form.cleaned_data["email"])
            return valid

        with patch.object(RegistrationForm, "is_valid", validate_then_competing_signup):
            response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertContains(response, "An account with this email address already exists.")
        self.assertEqual(User.objects.count(), 1)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_non_field_errors_are_displayed(self):
        original_clean = RegistrationForm.clean

        def clean_with_error(form):
            original_clean(form)
            raise ValidationError("Please review your registration details.")

        with patch.object(RegistrationForm, "clean", clean_with_error):
            response = self.client.post(self.url, self.data)
        self.assertContains(response, "Please review your registration details.")
        self.assertEqual(User.objects.count(), 0)

    def test_post_requires_csrf_token(self):
        from django.test import Client

        response = Client(enforce_csrf_checks=True).post(self.url, self.data)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.count(), 0)
