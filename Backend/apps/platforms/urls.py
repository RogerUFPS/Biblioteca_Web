from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("public", views.PlatformPublicViewSet, basename="platform-public")
router.register("valid-sintaxis", views.ValidSintaxisViewSet, basename="valid-sintaxis")
router.register("link-check-logs", views.LinkCheckLogViewSet, basename="link-check-log")
router.register("", views.PlatformViewSet, basename="platform")

urlpatterns = router.urls
