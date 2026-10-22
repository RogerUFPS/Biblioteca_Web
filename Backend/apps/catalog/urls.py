from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("institutions", views.InstitutionViewSet, basename="institution")
router.register("languages", views.LanguageViewSet, basename="language")
router.register("countries", views.CountryViewSet, basename="country")
router.register("material-types", views.MaterialTypeViewSet, basename="material-type")
router.register("editorials", views.EditorialViewSet, basename="editorial")
router.register("knowledge-areas", views.KnowledgeAreaViewSet, basename="knowledge-area")
router.register("academic-programs", views.AcademicProgramViewSet, basename="academic-program")

urlpatterns = router.urls
