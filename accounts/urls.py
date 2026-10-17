from django.urls import path
from saved_rooms import views as saved_views

from . import verification_views, notification_views, agreement_views, profile_views, request_views, tenant_views, views

app_name = "accounts"

urlpatterns = [
    path("verify-email/resend/", verification_views.resend_email, name="resend_email"),
    path("verify-email/<str:token>/", verification_views.verify_email, name="verify_email"),
    path("tenant/identity/<int:pk>/<str:side>/", verification_views.tenant_identity_document, name="tenant_identity_document"),
    path("tenant/notifications/read/", notification_views.mark_read, name="notifications_read_all"),
    path("tenant/notifications/<int:pk>/read/", notification_views.mark_read, name="notification_read"),
    path("tenant/agreements/", agreement_views.my_agreements, name="my_agreements"),
    path("tenant/requests/", request_views.my_requests, name="my_requests"),
    path("tenant/saved/", saved_views.saved_rooms, name="saved_rooms"),
    path("tenant/rooms/<int:pk>/save/", saved_views.change_saved_room, name="change_saved_room"),
    path("tenant/profile/picture/", profile_views.profile_picture, name="profile_picture"),
    path("tenant/profile/", profile_views.tenant_profile, name="tenant_profile"),
    path("tenant/", tenant_views.home, name="tenant"),
    path("tenant/rooms/", tenant_views.find_rooms, name="find_rooms"),
    path("tenant/rooms/<int:pk>/", tenant_views.room_details, name="room_details"),
    path("tenant/photos/<int:pk>/", tenant_views.listing_photo, name="tenant_photo"),
    path("owner/", views.owner_area, name="owner"),
    path("admin/", views.admin_area, name="admin"),
    path("verification/", views.verification, name="verification"),
    path("verification/<int:pk>/document/", views.verification_document, name="verification_document"),
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("register/", views.register, name="register"),
]
