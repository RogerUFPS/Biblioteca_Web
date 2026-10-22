from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf/", views.CsrfView.as_view(), name="account-csrf"),
    path("auth/login/", views.LoginView.as_view(), name="account-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="account-logout"),
    path("auth/me/", views.MeView.as_view(), name="account-me"),
    path("register/", views.RegisterView.as_view(), name="account-register"),
    path("password/change/", views.ChangePasswordView.as_view(), name="password-change"),
    path("password/forgot/", views.ForgotPasswordView.as_view(), name="password-forgot"),
    path("users/", views.UsersView.as_view(), name="account-users"),
    path(
        "users/archived/",
        views.ArchivedUsersView.as_view(),
        name="account-archived-users",
    ),
    path("users/invite/", views.InviteView.as_view(), name="account-user-invite"),
    path(
        "users/<int:pk>/",
        views.UserDetailView.as_view(),
        name="account-user-detail",
    ),
    path(
        "users/<int:pk>/restore/",
        views.UserRestoreView.as_view(),
        name="account-user-restore",
    ),
    path(
        "users/<int:pk>/permissions/",
        views.UserPermissionsView.as_view(),
        name="account-user-permissions",
    ),
    path(
        "users/<int:pk>/presets/",
        views.UserPresetsView.as_view(),
        name="account-user-presets",
    ),
    path("presets/", views.PresetsView.as_view(), name="account-presets"),
    path(
        "presets/<int:pk>/",
        views.PresetDetailView.as_view(),
        name="account-preset-detail",
    ),
    path("permissions/", views.PermissionsView.as_view(), name="account-permissions"),
]
