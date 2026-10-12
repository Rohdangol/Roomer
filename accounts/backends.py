from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, *, email=None, **kwargs):
        # Only explicit email credentials belong here; admin usernames use ModelBackend.
        if email is None or password is None:
            return None
        User = get_user_model()
        email = User.objects.normalize_email(email)
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Match Django's dummy hash to reduce unknown-account timing differences.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
