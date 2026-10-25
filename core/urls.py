from django.urls import path
from . import views

urlpatterns = [
    path("about/", views.empty_page, name="about"),
    path("contact/", views.empty_page, name="contact"),
    path("privacy/", views.empty_page, name="privacy"),
    path("neighbourhood/", views.empty_page, name="neighbourhood"),
    path("", views.home, name="home"),
]
