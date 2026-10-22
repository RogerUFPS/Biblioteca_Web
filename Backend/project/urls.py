from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)


urlpatterns = [
    path(
        "api/accounts/",
        include("apps.account.urls"),
    ),
    path(
        "admin/",
        admin.site.urls,
    ),
    path(
        "api/catalog/",
        include("apps.catalog.urls"),
    ),
    path(
        "api/platforms/",
        include("apps.platforms.urls"),
    ),
    path(
        "api/journals/",
        include("apps.journal.urls"),
    ),
    path(
        "api/harvesting/",
        include("apps.harvesting.urls"),
    ),
    path(
        "api/audit/",
        include("apps.audit.urls"),
    ),

    # OpenAPI / Swagger
    path(
        "api/schema/",
        SpectacularAPIView.as_view(),
        name="schema",
    ),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(
            url_name="schema",
        ),
        name="swagger-ui",
    ),
]
