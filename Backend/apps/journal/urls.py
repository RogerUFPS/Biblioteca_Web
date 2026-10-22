from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()

router.register(
    "public",
    views.JournalPublicViewSet,
    basename="journal-public",
)

router.register(
    "licenses",
    views.LicenseViewSet,
    basename="journal-license",
)

router.register(
    "",
    views.JournalViewSet,
    basename="journal",
)


urlpatterns = router.urls
