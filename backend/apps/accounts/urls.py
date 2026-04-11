"""Auth URL routes."""
from django.urls import path

from .views import (
    LoginView,
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RefreshView,
)

app_name = "accounts"

urlpatterns = [
    path("login/",                   LoginView.as_view(),               name="login"),
    path("refresh/",                 RefreshView.as_view(),              name="refresh"),
    path("logout/",                  LogoutView.as_view(),               name="logout"),
    path("me/",                      MeView.as_view(),                   name="me"),
    path("password-reset/",          PasswordResetRequestView.as_view(), name="password-reset"),
    path("password-reset/confirm/",  PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
]
