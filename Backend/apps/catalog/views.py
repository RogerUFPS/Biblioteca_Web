from apps.core.viewsets import AuditableViewSet, get_acting_user

from . import models, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view
from apps.journal import models as journal_models
from apps.platforms import models as platform_models


IN_USE_MESSAGE = (
    "No se puede eliminar el registro porque está siendo utilizado por otros "
    "registros vigentes."
)


class ProtectedCatalogViewSet(AuditableViewSet):
    platform_through = None
    platform_relation_field = None
    journal_through = None
    journal_relation_field = None

    def active_business_dependencies(self, instance):
        return []

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if any(self.active_business_dependencies(instance)):
            return Response({"detail": IN_USE_MESSAGE}, status=400)
        return super().destroy(request, *args, **kwargs)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        platform_id = self.request.query_params.get("platform")
        available_for = self.request.query_params.get("available_for_platform")
        journal_id = self.request.query_params.get("journal")
        available_for_journal = self.request.query_params.get(
            "available_for_journal"
        )
        origin = self.request.query_params.get("origin")
        editable = self.request.query_params.get("editable")
        if platform_id and journal_id:
            raise ValidationError({
                "detail": "Use un solo contexto: platform o journal."
            })
        if (origin or editable is not None) and not (platform_id or journal_id):
            raise ValidationError({
                "detail": "Este filtro requiere platform o journal."
            })
        if origin and origin not in {"manual", "derived", "both"}:
            raise ValidationError({"origin": "Use manual, derived o both."})
        through, field = self.platform_through, self.platform_relation_field
        if through is not None and available_for:
            used = through.objects.filter(platform_id=available_for).values_list(
                f"{field}_id", flat=True
            )
            queryset = queryset.exclude(pk__in=used)
        if through is not None and platform_id:
            relations = through.objects.filter(platform_id=platform_id)
            if origin == "manual":
                relations = relations.filter(is_manual=True, is_derived=False)
            elif origin == "derived":
                relations = relations.filter(is_manual=False, is_derived=True)
            elif origin == "both":
                relations = relations.filter(is_manual=True, is_derived=True)
            if editable is not None:
                if editable.lower() not in {"true", "false"}:
                    raise ValidationError({"editable": "Use true o false."})
                editable_relations = through.objects.filter(
                    platform_id=platform_id, is_manual=True, is_derived=False,
                )
                if editable.lower() == "true":
                    relations = editable_relations
                else:
                    relations = relations.exclude(
                        pk__in=editable_relations.values_list("pk", flat=True)
                    )
                queryset = queryset.filter(
                    pk__in=relations.values_list(f"{field}_id", flat=True)
                )
            else:
                queryset = queryset.filter(
                    pk__in=relations.values_list(f"{field}_id", flat=True)
                )
        journal_through = self.journal_through
        journal_field = self.journal_relation_field
        if journal_through is not None and available_for_journal:
            used = journal_through.objects.filter(
                journal_id=available_for_journal
            ).values_list(f"{journal_field}_id", flat=True)
            queryset = queryset.exclude(pk__in=used)
        if journal_through is not None and journal_id:
            relations = journal_through.objects.filter(journal_id=journal_id)
            if origin == "manual":
                relations = relations.filter(is_manual=True, is_derived=False)
            elif origin == "derived":
                relations = relations.filter(is_manual=False, is_derived=True)
            elif origin == "both":
                relations = relations.filter(is_manual=True, is_derived=True)
            if editable is not None:
                if editable.lower() not in {"true", "false"}:
                    raise ValidationError({"editable": "Use true o false."})
                editable_relations = journal_through.objects.filter(
                    journal_id=journal_id,
                    is_manual=True,
                    is_derived=False,
                )
                if editable.lower() == "true":
                    relations = editable_relations
                else:
                    relations = relations.exclude(
                        pk__in=editable_relations.values_list("pk", flat=True)
                    )
            queryset = queryset.filter(
                pk__in=relations.values_list(f"{journal_field}_id", flat=True)
            )
        return queryset.distinct()


class InstitutionViewSet(ProtectedCatalogViewSet):
    platform_through = platform_models.SharedPlatformSupport
    platform_relation_field = "institution"
    queryset = models.Institution.objects.all()
    serializer_class = serializers.InstitutionSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]

    def active_business_dependencies(self, instance):
        return [instance.platform_support_links.filter(platform__deleted_at__isnull=True).exists()]


class LanguageViewSet(ProtectedCatalogViewSet):
    platform_through = platform_models.SharedPlatformLanguage
    platform_relation_field = "language"
    queryset = models.Language.objects.all()
    serializer_class = serializers.LanguageSerializer
    search_fields = ["name", "abbreviation"]
    ordering_fields = ["name", "abbreviation", "created_at"]

    def active_business_dependencies(self, instance):
        return [instance.journal_links.filter(journal__deleted_at__isnull=True).exists(), instance.platform_links.filter(platform__deleted_at__isnull=True).exists()]


class CountryViewSet(ProtectedCatalogViewSet):
    platform_through = platform_models.SharedPlatformCountry
    platform_relation_field = "country"
    queryset = models.Country.objects.all()
    serializer_class = serializers.CountrySerializer
    search_fields = ["name", "abbreviation"]
    ordering_fields = ["name", "abbreviation", "created_at"]

    def active_business_dependencies(self, instance):
        return [instance.journal_links.filter(journal__deleted_at__isnull=True).exists(), instance.platform_links.filter(platform__deleted_at__isnull=True).exists()]


class MaterialTypeViewSet(ProtectedCatalogViewSet):
    platform_through = platform_models.SharedPlatformMaterialType
    platform_relation_field = "material_type"
    queryset = models.MaterialType.objects.all()
    serializer_class = serializers.MaterialTypeSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]

    def active_business_dependencies(self, instance):
        return [instance.journal_links.filter(journal__deleted_at__isnull=True).exists(), instance.platform_links.filter(platform__deleted_at__isnull=True).exists()]


class EditorialViewSet(ProtectedCatalogViewSet):
    queryset = models.Editorial.objects.all()
    serializer_class = serializers.EditorialSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]

    def active_business_dependencies(self, instance):
        return [instance.journals.filter(deleted_at__isnull=True).exists()]


@extend_schema_view(
    list=extend_schema(parameters=[
        OpenApiParameter(
            "journal", OpenApiTypes.INT, OpenApiParameter.QUERY,
            description="Journal usada como contexto de procedencia.",
        ),
        OpenApiParameter(
            "origin", OpenApiTypes.STR, OpenApiParameter.QUERY,
            description="Origen contextual: manual, derived o both.",
        ),
        OpenApiParameter(
            "editable", OpenApiTypes.BOOL, OpenApiParameter.QUERY,
            description="Filtra áreas editables o protegidas en la Journal.",
        ),
        OpenApiParameter(
            "available_for_journal", OpenApiTypes.INT, OpenApiParameter.QUERY,
            description="Excluye áreas con relación vigente en la Journal.",
        ),
    ]),
)
class KnowledgeAreaViewSet(ProtectedCatalogViewSet):
    platform_through = platform_models.SharedPlatformKnowledgeArea
    platform_relation_field = "knowledge_area"
    journal_through = journal_models.SharedJournalKnowledgeArea
    journal_relation_field = "knowledge_area"
    queryset = models.KnowledgeArea.objects.all()
    serializer_class = serializers.KnowledgeAreaSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]

    def active_business_dependencies(self, instance):
        return [instance.journal_links.filter(journal__deleted_at__isnull=True).exists(), instance.platform_links.filter(platform__deleted_at__isnull=True).exists(), instance.program_links.filter(academic_program__deleted_at__isnull=True).exists()]

    def destroy(self, request, *args, **kwargs):
        area = self.get_object()
        program_ids = set(
            models.SharedAcademicProgramKnowledgeArea.objects.filter(
                knowledge_area=area,
            ).values_list("academic_program_id", flat=True)
        )
        response = super().destroy(request, *args, **kwargs)
        if response.status_code < 400 and program_ids:
            from apps.journal.classification import propagate_catalog_change
            propagate_catalog_change(program_ids, user=get_acting_user(request))
        return response

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        response = super().restore(request, pk=pk)
        if response.status_code < 400:
            program_ids = set(
                models.SharedAcademicProgramKnowledgeArea.objects.filter(
                    knowledge_area_id=pk,
                ).values_list("academic_program_id", flat=True)
            )
            from apps.journal.classification import propagate_catalog_change
            propagate_catalog_change(program_ids, user=get_acting_user(request))
        return response

    @action(detail=True, methods=["get"], url_path="academic-programs")
    def academic_programs(self, request, pk=None):
        area = self.get_object()
        queryset = models.AcademicProgram.objects.filter(
            knowledge_area_links__knowledge_area=area,
        )
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)
        serializer = serializers.AcademicProgramSerializer(
            page if page is not None else queryset,
            many=True,
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class AcademicProgramViewSet(ProtectedCatalogViewSet):
    platform_through = platform_models.SharedPlatformAcademicProgram
    platform_relation_field = "academic_program"
    queryset = models.AcademicProgram.objects.all()
    serializer_class = serializers.AcademicProgramSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]

    def active_business_dependencies(self, instance):
        return [
            instance.journal_links.filter(journal__deleted_at__isnull=True).exists(),
            instance.platform_links.filter(platform__deleted_at__isnull=True).exists(),
            instance.knowledge_area_links.filter(
                knowledge_area__deleted_at__isnull=True,
            ).exists(),
        ]

    def destroy(self, request, *args, **kwargs):
        program = self.get_object()
        program_id = program.pk
        response = super().destroy(request, *args, **kwargs)
        if response.status_code < 400:
            from apps.journal.classification import propagate_catalog_change
            propagate_catalog_change([program_id], user=get_acting_user(request))
        return response

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        response = super().restore(request, pk=pk)
        if response.status_code < 400:
            from apps.journal.classification import propagate_catalog_change
            propagate_catalog_change([int(pk)], user=get_acting_user(request))
        return response

    @action(detail=True, methods=["get"], url_path="knowledge-areas")
    def knowledge_areas(self, request, pk=None):
        program = self.get_object()
        queryset = models.KnowledgeArea.objects.filter(
            program_links__academic_program=program,
        )
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)
        serializer = serializers.KnowledgeAreaSerializer(
            page if page is not None else queryset,
            many=True,
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
