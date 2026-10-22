from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.viewsets import (
    AuditableViewSet,
    DeleteSerializer,
    get_acting_user,
)

from . import filters, models, serializers, services
from apps.platforms.classification import recalculate_platforms
from apps.platforms import models as platform_models
from apps.platforms import services as platform_services
from .classification import related_platform_ids


class LicenseViewSet(AuditableViewSet):
    queryset = models.License.objects.all()
    serializer_class = serializers.LicenseSerializer
    search_fields = ["name"]
    ordering_fields = ["name", "created_at", "updated_at"]

    def destroy(self, request, *args, **kwargs):
        license_instance = self.get_object()
        if license_instance.journal_links.filter(journal__deleted_at__isnull=True).exists():
            return Response(
                {"detail": (
                    "No se puede eliminar el registro porque está siendo utilizado "
                    "por otros registros vigentes."
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


def _with_platform_urls(queryset, *, published_only=False):
    platform_links = (
        models.SharedJournalPlatform.objects
        .filter(platform__deleted_at__isnull=True)
        .select_related("platform")
        .prefetch_related(
            Prefetch(
                "platform__link_check_logs",
                queryset=(
                    platform_models.LinkCheckLog.objects
                    .filter(journal_platform__isnull=True)
                    .order_by(*platform_services.LINK_LOG_ORDERING)
                ),
                to_attr="_public_link_logs",
            ),
            Prefetch(
                "link_check_logs",
                queryset=(
                    platform_models.LinkCheckLog.objects
                    .order_by(*platform_services.LINK_LOG_ORDERING)
                ),
                to_attr="_journal_link_logs",
            ),
        )
        .order_by("platform__name")
    )
    if published_only:
        platform_links = platform_links.filter(
            platform__status=platform_models.Platform.Status.PUBLICADO
        )

    return queryset.prefetch_related(
        Prefetch(
            "platform_links",
            queryset=platform_links,
            to_attr="_url_platform_links",
        )
    )


@extend_schema_view(
    list=extend_schema(
        summary="Listar revistas",
        description=(
            "Obtiene el listado administrativo de revistas "
            "registradas en el sistema."
        ),
        tags=["Revistas - Administración"],
    ),
    retrieve=extend_schema(
        summary="Consultar revista",
        description=(
            "Obtiene el detalle administrativo de una revista."
        ),
        tags=["Revistas - Administración"],
    ),
    create=extend_schema(
        summary="Crear revista",
        description=(
            "Registra manualmente una nueva revista académica."
        ),
        request=serializers.JournalSerializer,
        responses={
            201: serializers.JournalSerializer,
        },
        tags=["Revistas - Administración"],
    ),
    update=extend_schema(
        summary="Actualizar revista",
        description=(
            "Actualiza completamente la información "
            "de una revista."
        ),
        request=serializers.JournalSerializer,
        responses={
            200: serializers.JournalSerializer,
        },
        tags=["Revistas - Administración"],
    ),
    partial_update=extend_schema(
        summary="Actualizar parcialmente una revista",
        description=(
            "Actualiza uno o varios campos de una revista."
        ),
        request=serializers.JournalSerializer,
        responses={
            200: serializers.JournalSerializer,
        },
        tags=["Revistas - Administración"],
    ),
    destroy=extend_schema(
        summary="Eliminar revista",
        description=(
            "Retira una revista mediante eliminación lógica "
            "(Soft Delete). Si la revista tiene relaciones de negocio, "
            "debe enviarse una explicación de eliminación en el cuerpo "
            "de la solicitud. Si no tiene dependencias, puede eliminarse "
            "sin cuerpo."
        ),
        responses={
            200: inline_serializer(
                name="JournalSoftDeleteResponse",
                fields={
                    "detail": drf_serializers.CharField(),
                    "permanent": drf_serializers.BooleanField(),
                },
            ),
            204: None,
            400: inline_serializer(
                name="JournalDeleteValidationError",
                fields={
                    "detail": drf_serializers.CharField(
                        required=False,
                    ),
                    "delete_explanation": drf_serializers.ListField(
                        child=drf_serializers.CharField(),
                        required=False,
                    ),
                },
            ),
        },
        tags=["Revistas - Administración"],
    ),
)
class JournalViewSet(AuditableViewSet):
    """
    CRUD administrativo y ciclo de validación
    de revistas académicas.
    """

    queryset = _with_platform_urls(models.Journal.objects.all())

    serializer_class = serializers.JournalSerializer

    search_fields = [
        "title",
        "issn",
    ]

    filterset_class = filters.JournalFilter

    ordering_fields = [
        "title",
        "issn",
        "publication_date",
        "created_at",
        "updated_at",
        "fetched_at",
    ]

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        journal = self.get_object()
        body = DeleteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        user = get_acting_user(request)
        platform_ids = related_platform_ids([journal.pk])
        journal.soft_delete(
            user=user,
            explanation=body.validated_data["delete_explanation"],
        )
        journal.active = False
        journal.validated_by = None
        journal.validated_at = None
        journal.updated_by = user
        journal.updated_at = timezone.now()
        journal.save(update_fields=[
            "active", "validated_by", "validated_at", "updated_by", "updated_at",
        ])
        recalculate_platforms(platform_ids, user=user)
        return Response(
            {"detail": "La revista fue eliminada lógicamente.", "permanent": False},
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Validar y publicar revista",
        description=(
            "Valida explícitamente la ficha de una revista "
            "y la habilita para consulta pública."
        ),
        request=serializers.JournalPublishSerializer,
        responses={
            200: serializers.JournalSerializer,
        },
        tags=["Revistas - Administración"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
    )
    @transaction.atomic
    def publish(self, request, pk=None):
        journal = self.get_object()
        user = get_acting_user(request)
        now = timezone.now()
        body = serializers.JournalPublishSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        if "licenses" in body.validated_data:
            selected = {item.pk for item in body.validated_data["licenses"]}
            existing = {
                link.license_id: link
                for link in models.SharedJournalLicense.all_objects.filter(journal=journal)
            }
            for license_id, link in existing.items():
                if license_id in selected:
                    if link.is_deleted:
                        link.restore()
                elif not link.is_deleted:
                    link.soft_delete(
                        user=user,
                        explanation="Licencia retirada durante la publicación.",
                    )
            for license_id in selected - existing.keys():
                models.SharedJournalLicense.objects.create(
                    journal=journal,
                    license_id=license_id,
                    created_by=user,
                )

        services.validate_journal_for_publication(journal)

        journal.active = True
        journal.validated_by = user
        journal.validated_at = now
        journal.updated_by = user
        journal.updated_at = now

        journal.save(
            update_fields=[
                "active",
                "validated_by",
                "validated_at",
                "updated_by",
                "updated_at",
            ]
        )
        recalculate_platforms(related_platform_ids([journal.pk]), user=user)

        return Response(
            self.get_serializer(journal).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Listar asociaciones vigentes con plataformas",
        parameters=[OpenApiParameter(
            name="platform_is_public",
            type=OpenApiTypes.BOOL,
            location=OpenApiParameter.QUERY,
            required=False,
        )],
        responses={200: drf_serializers.ListSerializer(
            child=drf_serializers.DictField(),
        )},
        tags=["Revistas - Administración"],
    )
    @action(detail=True, methods=["get"], url_path="platforms")
    def platform_associations(self, request, pk=None):
        journal = self.get_object()
        links = models.SharedJournalPlatform.objects.filter(
            journal=journal,
            platform__deleted_at__isnull=True,
        ).select_related("platform")
        raw_public = request.query_params.get("platform_is_public")
        if raw_public is not None:
            if raw_public.lower() not in {"true", "false"}:
                return Response(
                    {"platform_is_public": "Use true o false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            is_public = raw_public.lower() == "true"
            lookup = {"platform__status": platform_models.Platform.Status.PUBLICADO}
            links = links.filter(**lookup) if is_public else links.exclude(**lookup)
        return Response([
            serializers._represent_journal_platform(link, include_relation_key=True)
            for link in links.order_by("platform__name")
        ])

    @extend_schema(
        summary="Desactivar revista",
        description=(
            "Marca una revista como inactiva. "
            "Una revista inactiva deja de estar disponible "
            "en la exploración pública."
        ),
        request=None,
        responses={
            200: serializers.JournalSerializer,
        },
        tags=["Revistas - Administración"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="deactivate",
    )
    @transaction.atomic
    def deactivate(self, request, pk=None):
        journal = self.get_object()
        user = get_acting_user(request)
        now = timezone.now()

        journal.active = False
        journal.updated_by = user
        journal.updated_at = now

        journal.save(
            update_fields=[
                "active",
                "updated_by",
                "updated_at",
            ]
        )
        recalculate_platforms(related_platform_ids([journal.pk]), user=user)

        return Response(
            self.get_serializer(journal).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Restaurar revista eliminada",
        description=(
            "Restaura una revista eliminada mediante Soft Delete. "
            "La revista restaurada pierde su validación previa y "
            "debe publicarse nuevamente."
        ),
        request=None,
        responses={
            200: serializers.JournalSerializer,
            404: None,
        },
        tags=["Revistas - Administración"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="restore",
    )
    @transaction.atomic
    def restore(self, request, pk=None):
        model = self.queryset.model

        try:
            journal = model.all_objects.get(
                pk=pk,
                deleted_at__isnull=False,
            )
        except (model.DoesNotExist, ValueError):
            return Response(
                {
                    "detail": (
                        "No existe una revista eliminada "
                        "con ese id."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        user = get_acting_user(request)
        now = timezone.now()

        journal.restore()

        # Una revista restaurada debe validarse nuevamente
        # antes de regresar a la exploración pública.
        journal.active = False
        journal.validated_by = None
        journal.validated_at = None
        journal.updated_by = user
        journal.updated_at = now

        journal.save(
            update_fields=[
                "active",
                "validated_by",
                "validated_at",
                "updated_by",
                "updated_at",
            ]
        )
        recalculate_platforms(related_platform_ids([journal.pk]), user=user)

        return Response(
            self.get_serializer(journal).data,
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    list=extend_schema(
        summary="Explorar revistas publicadas",
        description=(
            "Lista únicamente revistas activas y previamente "
            "validadas por el personal autorizado."
        ),
        tags=["Revistas - Público"],
    ),
    retrieve=extend_schema(
        summary="Consultar revista publicada",
        description=(
            "Obtiene la ficha pública de una revista activa "
            "y validada."
        ),
        tags=["Revistas - Público"],
    ),
)
class JournalPublicViewSet(
    viewsets.ReadOnlyModelViewSet
):
    """
    Exploración pública de revistas activas y validadas.
    """

    queryset = _with_platform_urls((
        models.Journal.objects
        .filter(
            active=True,
            validated_at__isnull=False,
        )
        .select_related(
            "editorial"
        )
        .distinct()
    ), published_only=True)

    serializer_class = (
        serializers.JournalPublicSerializer
    )

    filterset_class = (
        filters.JournalPublicFilter
    )

    search_fields = [
        "title",
        "issn",
    ]

    ordering_fields = [
        "title",
        "issn",
        "publication_date",
    ]
