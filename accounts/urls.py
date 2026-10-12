from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("tenant/", views.tenant_area, name="tenant"),
    path("owner/", views.owner_area, name="owner"),
    path("admin/", views.admin_area, name="admin"),
    path("verification/", views.verification, name="verification"),
    path("verification/<int:pk>/document/", views.verification_document, name="verification_document"),
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("register/", views.register, name="register"),
]
