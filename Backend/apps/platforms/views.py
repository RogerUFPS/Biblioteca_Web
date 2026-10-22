from django.db.models import F, Prefetch
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
    get_acting_user,
)
from apps.core.pagination import CustomPageNumberPagination

from . import classification, filters, models, serializers, services


def _with_public_link_logs(queryset):
    return queryset.prefetch_related(
        Prefetch(
            "link_check_logs",
            queryset=(
                models.LinkCheckLog.objects
                .filter(journal_platform__isnull=True)
                .order_by(*services.LINK_LOG_ORDERING)
            ),
            to_attr="_public_link_logs",
        )
    )


# ==============================================================================
# VALID SINTAXIS
# ==============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Listar sintaxis válidas",
        description=(
            "Obtiene el listado administrativo de sintaxis de búsqueda "
            "admitidas por las plataformas."
        ),
        tags=["Plataformas - Sintaxis"],
    ),
    retrieve=extend_schema(
        summary="Consultar sintaxis válida",
        description=(
            "Obtiene el detalle de una sintaxis de búsqueda válida."
        ),
        tags=["Plataformas - Sintaxis"],
    ),
    create=extend_schema(
        summary="Crear sintaxis válida",
        description=(
            "Registra una nueva sintaxis de búsqueda admitida."
        ),
        request=serializers.ValidSintaxisSerializer,
        responses={
            201: serializers.ValidSintaxisSerializer,
        },
        tags=["Plataformas - Sintaxis"],
    ),
    update=extend_schema(
        summary="Actualizar sintaxis válida",
        description=(
            "Actualiza completamente una sintaxis de búsqueda."
        ),
        request=serializers.ValidSintaxisSerializer,
        responses={
            200: serializers.ValidSintaxisSerializer,
        },
        tags=["Plataformas - Sintaxis"],
    ),
    partial_update=extend_schema(
        summary="Actualizar parcialmente sintaxis válida",
        description=(
            "Actualiza uno o varios campos de una sintaxis de búsqueda."
        ),
        request=serializers.ValidSintaxisSerializer,
        responses={
            200: serializers.ValidSintaxisSerializer,
        },
        tags=["Plataformas - Sintaxis"],
    ),
    destroy=extend_schema(
        summary="Eliminar sintaxis válida",
        description=(
            "Retira una sintaxis de búsqueda mediante eliminación lógica "
            "(Soft Delete)."
        ),
        responses={
            200: inline_serializer(
                name="ValidSintaxisSoftDeleteResponse",
                fields={
                    "detail": drf_serializers.CharField(),
                    "permanent": drf_serializers.BooleanField(),
                },
            ),
            204: None,
            400: inline_serializer(
                name="ValidSintaxisDeleteValidationError",
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
        tags=["Plataformas - Sintaxis"],
    ),
)
class ValidSintaxisViewSet(AuditableViewSet):
    """
    CRUD administrativo para la gestión de sintaxis de búsqueda admitidas.
    """

    queryset = models.ValidSintaxis.objects.all()
    serializer_class = serializers.ValidSintaxisSerializer

    search_fields = [
        "name",
    ]

    ordering_fields = [
        "name",
        "created_at",
    ]

    def destroy(self, request, *args, **kwargs):
        syntax = self.get_object()
        if syntax.platforms.filter(deleted_at__isnull=True).exists():
            return Response(
                {"detail": (
                    "No se puede eliminar el registro porque está siendo utilizado "
                    "por otros registros vigentes."
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        summary="Buscar sintaxis vigentes similares",
        request=serializers.ValidSintaxisSimilarityRequestSerializer,
        responses={200: inline_serializer(
            name="ValidSintaxisSimilarityResponse",
            fields={
                "results": serializers.ValidSintaxisSimilarityResultSerializer(many=True),
            },
        )},
        tags=["Plataformas - Sintaxis"],
    )
    @action(detail=False, methods=["post"], url_path="similar")
    def similar(self, request):
        body = serializers.ValidSintaxisSimilarityRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(
            {"results": services.similar_syntaxes(body.validated_data)},
            status=status.HTTP_200_OK,
        )


# ==============================================================================
# HISTORIAL DE VERIFICACIÓN DE ENLACES
# ==============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Listar verificaciones de enlaces",
        description=(
            "Obtiene el historial de verificaciones realizadas sobre "
            "los enlaces de las plataformas. Por defecto muestra primero "
            "las verificaciones más recientes y deja al final los registros "
            "todavía no verificados. Use journal_platform__isnull=true para "
            "consultar únicamente URLs públicas generales y "
            "verification_status=unverified|available|unavailable para "
            "distinguir su estado semántico."
        ),
        parameters=[
            OpenApiParameter(
                name="page_size",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Cantidad de registros por página. Valor predeterminado: "
                    "10; máximo permitido: 100."
                ),
            ),
        ],
        tags=["Plataformas - Verificación de enlaces"],
    ),
    retrieve=extend_schema(
        summary="Consultar verificación de enlace",
        description=(
            "Obtiene el detalle de una verificación de enlace."
        ),
        tags=["Plataformas - Verificación de enlaces"],
    ),
)
class LinkCheckLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Consulta de solo lectura del historial de verificaciones de enlaces.
    """

    queryset = models.LinkCheckLog.objects.order_by(
        F("last_check").desc(nulls_last=True),
        "-created_at",
        "-pk",
    )
    serializer_class = serializers.LinkCheckLogSerializer
    pagination_class = CustomPageNumberPagination

    filterset_class = filters.LinkCheckLogFilter

    ordering_fields = [
        "last_check",
        "fail_count",
        "created_at",
    ]


# ==============================================================================
# PLATAFORMAS - ADMINISTRACIÓN
# ==============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Listar plataformas",
        description=(
            "Obtiene el listado administrativo de plataformas "
            "registradas en el sistema."
        ),
        tags=["Plataformas - Administración"],
    ),
    retrieve=extend_schema(
        summary="Consultar plataforma",
        description=(
            "Obtiene el detalle administrativo de una plataforma."
        ),
        tags=["Plataformas - Administración"],
    ),
    create=extend_schema(
        summary="Crear plataforma",
        description=(
            "Registra una nueva plataforma de información académica."
        ),
        request=serializers.PlatformSerializer,
        responses={
            201: serializers.PlatformSerializer,
        },
        tags=["Plataformas - Administración"],
    ),
    update=extend_schema(
        summary="Actualizar plataforma",
        description=(
            "Actualiza completamente la información de una plataforma."
        ),
        request=serializers.PlatformSerializer,
        responses={
            200: serializers.PlatformSerializer,
        },
        tags=["Plataformas - Administración"],
    ),
    partial_update=extend_schema(
        summary="Actualizar parcialmente una plataforma",
        description=(
            "Actualiza uno o varios campos de una plataforma."
        ),
        request=serializers.PlatformSerializer,
        responses={
            200: serializers.PlatformSerializer,
        },
        tags=["Plataformas - Administración"],
    ),
    destroy=extend_schema(
        summary="Eliminar plataforma",
        description=(
            "Retira una plataforma mediante eliminación lógica "
            "(Soft Delete). Si la plataforma tiene relaciones de negocio, "
            "debe enviarse una explicación de eliminación en el cuerpo "
            "de la solicitud."
        ),
        responses={
            200: inline_serializer(
                name="PlatformSoftDeleteResponse",
                fields={
                    "detail": drf_serializers.CharField(),
                    "permanent": drf_serializers.BooleanField(),
                },
            ),
            204: None,
            400: inline_serializer(
                name="PlatformDeleteValidationError",
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
        tags=["Plataformas - Administración"],
    ),
)
class PlatformViewSet(AuditableViewSet):
    """
    CRUD y ciclo de vida administrativo de plataformas.
    """

    queryset = _with_public_link_logs(models.Platform.objects.all())
    serializer_class = serializers.PlatformSerializer

    search_fields = [
        "name",
    ]

    filterset_class = filters.PlatformFilter

    ordering_fields = [
        "name",
        "status",
        "start_period",
        "finish_period",
        "created_at",
    ]

    def destroy(self, request, *args, **kwargs):
        platform = self.get_object()
        if platform.journal_links.filter(journal__deleted_at__isnull=True).exists():
            return Response(
                {"detail": (
                    "No se puede eliminar la plataforma porque tiene revistas "
                    "asociadas. Desvincule primero las revistas de la plataforma."
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        summary="Publicar plataforma",
        description=(
            "Cambia el estado de una plataforma a PUBLICADO y registra "
            "la validación correspondiente. Una plataforma publicada "
            "puede estar disponible para la exploración pública."
        ),
        request=None,
        responses={
            200: serializers.PlatformSerializer,
        },
        tags=["Plataformas - Administración"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
    )
    def publish(self, request, pk=None):
        instance = self.get_object()
        user = get_acting_user(request)

        updated_platform = services.publish_platform(
            platform=instance,
            user=user,
        )

        return Response(
            self.get_serializer(updated_platform).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Marcar plataforma como obsoleta",
        description=(
            "Cambia el estado de una plataforma a OBSOLETO. "
            "La plataforma deja de considerarse publicada y el sistema "
            "registra automáticamente su fecha de obsolescencia."
        ),
        request=None,
        responses={
            200: serializers.PlatformSerializer,
        },
        tags=["Plataformas - Administración"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="mark-obsolete",
    )
    def mark_obsolete(self, request, pk=None):
        instance = self.get_object()
        user = get_acting_user(request)

        updated_platform = services.mark_platform_obsolete(
            platform=instance,
            user=user,
        )

        return Response(
            self.get_serializer(updated_platform).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Reactivar plataforma",
        description=(
            "Reactiva una plataforma previamente marcada como obsoleta "
            "y la devuelve al estado BORRADOR para una nueva validación. "
            "La fecha de obsolescencia se limpia automáticamente."
        ),
        request=None,
        responses={
            200: serializers.PlatformSerializer,
        },
        tags=["Plataformas - Administración"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="reactivate",
    )
    def reactivate(self, request, pk=None):
        instance = self.get_object()
        user = get_acting_user(request)

        updated_platform = services.reactivate_platform(
            platform=instance,
            user=user,
        )

        return Response(
            self.get_serializer(updated_platform).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Verificar enlace de plataforma",
        description=(
            "Verifica la URL pública de la plataforma y registra el "
            "resultado de la comprobación. Si se envía una URL, esta "
            "se registra y verifica. Si no se envía, se utiliza la "
            "última URL pública registrada para la plataforma."
        ),
        request=inline_serializer(
            name="PlatformLinkCheckRequest",
            fields={
                "url": drf_serializers.URLField(
                    required=False,
                    allow_null=True,
                    help_text=(
                        "URL pública de la plataforma. Si se omite, "
                        "se utiliza la última URL registrada."
                    ),
                ),
            },
        ),
        responses={
            200: serializers.LinkCheckLogSerializer,
        },
        tags=["Plataformas - Verificación de enlaces"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="check-link",
    )
    def check_link(self, request, pk=None):
        instance = self.get_object()
        user = get_acting_user(request)

        url = request.data.get("url")

        if url is not None and not isinstance(url, str):
            return Response(
                {
                    "url": "La URL debe ser una cadena de texto."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        link_log = services.check_platform_link(
            platform=instance,
            user=user,
            url=url,
        )

        return Response(
            serializers.LinkCheckLogSerializer(link_log).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Verificar todos los enlaces vigentes de una plataforma",
        operation_id="platform_check_links",
        request=None,
        responses={200: serializers.PlatformLinksCheckResponseSerializer},
        tags=["Plataformas - Verificación de enlaces"],
    )
    @action(detail=True, methods=["post"], url_path="check-links")
    def check_links(self, request, pk=None):
        result = services.check_platform_links(
            platform=self.get_object(),
            user=get_acting_user(request),
        )
        data = serializers.PlatformLinksCheckResponseSerializer(result).data
        return Response(data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Verificar todos los enlaces vigentes del sistema",
        operation_id="platform_check_links_global",
        request=None,
        responses={204: None},
        tags=["Plataformas - Verificación de enlaces"],
    )
    @action(detail=False, methods=["post"], url_path="check-links")
    def check_all_links(self, request):
        services.check_all_current_links(user=get_acting_user(request))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Restaurar plataforma eliminada",
        description=(
            "Restaura una plataforma eliminada mediante Soft Delete. "
            "La plataforma restaurada regresa al estado BORRADOR, "
            "pierde su validación previa y debe ser publicada nuevamente."
        ),
        request=None,
        responses={
            200: serializers.PlatformSerializer,
            404: None,
        },
        tags=["Plataformas - Administración"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="restore",
    )
    def restore(self, request, pk=None):
        model = self.queryset.model

        try:
            instance = model.all_objects.get(
                pk=pk,
                deleted_at__isnull=False,
            )
        except (model.DoesNotExist, ValueError):
            return Response(
                {
                    "detail": (
                        "No existe un registro eliminado con ese id."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        acting_user = get_acting_user(request)

        instance.restore()

        # Regla de negocio:
        # una plataforma restaurada regresa a borrador
        # y requiere nueva validación.
        instance.status = models.Platform.Status.BORRADOR
        instance.validated_by = None
        instance.validated_at = None
        instance.updated_by = acting_user
        instance.updated_at = timezone.now()

        instance.save(
            update_fields=[
                "status",
                "validated_by",
                "validated_at",
                "updated_by",
                "updated_at",
            ]
        )
        classification.recalculate_platforms([instance.pk], user=acting_user)

        return Response(
            self.get_serializer(instance).data,
            status=status.HTTP_200_OK,
        )


# ==============================================================================
# PLATAFORMAS - PÚBLICO
# ==============================================================================

@extend_schema_view(
    list=extend_schema(
        summary="Explorar plataformas publicadas",
        description=(
            "Lista únicamente plataformas publicadas y no eliminadas."
        ),
        tags=["Plataformas - Público"],
    ),
    retrieve=extend_schema(
        summary="Consultar plataforma publicada",
        description=(
            "Obtiene la ficha pública de una plataforma publicada "
            "y no eliminada."
        ),
        tags=["Plataformas - Público"],
    ),
)
class PlatformPublicViewSet(
    viewsets.ReadOnlyModelViewSet
):
    """
    Exploración pública de plataformas publicadas y no eliminadas.
    """

    queryset = _with_public_link_logs(
        models.Platform.objects.filter(
            status=models.Platform.Status.PUBLICADO,
        ).distinct()
    )

    serializer_class = serializers.PlatformPublicSerializer

    filterset_class = filters.PlatformPublicFilter

    search_fields = [
        "name",
    ]

    ordering_fields = [
        "name",
        "start_period",
        "finish_period",
    ]
