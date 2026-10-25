"""Auth URL routes."""
from django.urls import path

from .views import (
    ChangePasswordView,
    ClientIpDebugView,
    LoginView,
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    RefreshView,
)
from .views_audit import ActivityLogView
from .views_settings import LoginAuditView

app_name = "accounts"

urlpatterns = [
    path("login/",                   LoginView.as_view(),               name="login"),
    path("refresh/",                 RefreshView.as_view(),              name="refresh"),
    path("logout/",                  LogoutView.as_view(),               name="logout"),
    path("me/",                      MeView.as_view(),                   name="me"),
    path("change-password/",         ChangePasswordView.as_view(),       name="change-password"),
    path("password-reset/",          PasswordResetRequestView.as_view(), name="password-reset"),
    path("password-reset/confirm/",  PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("login-audit/",             LoginAuditView.as_view(),           name="login-audit"),
    path("activity/",                ActivityLogView.as_view(),          name="activity"),
    path("client-ip/",               ClientIpDebugView.as_view(),        name="client-ip"),
]
