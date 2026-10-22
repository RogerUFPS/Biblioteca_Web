from auditlog.registry import auditlog
from django.contrib.contenttypes.models import ContentType
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.pagination import CustomPageNumberPagination
from .filters import AuditLogFilter
from .models import AuditLog
from .serializers import (
    AuditActionSerializer,
    AuditLogDetailSerializer,
    AuditLogListSerializer,
    AuditResourceSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Auditoría"],
        summary="Listar registros de auditoría",
        description=(
            "Consulta el historial paginado de auditoría de todas las tablas y modelos de la base de datos. "
            "Permite auditar creaciones, actualizaciones y eliminaciones. "
            "Si las modificaciones se realizaron sin un usuario autenticado (sin cuentas creadas previamente), "
            "la llave foránea del usuario se almacena como nula (actor = null). "
            "Los registros son inmutables y de solo lectura."
        ),
    ),
    retrieve=extend_schema(
        tags=["Auditoría"],
        summary="Consultar detalle de un registro de auditoría",
        description=(
            "Obtiene el detalle completo de un registro de auditoría, incluyendo el diccionario JSON de cambios "
            "(`changes`) que refleja los valores anteriores y nuevos para cada campo modificado."
        ),
    ),
)
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet inmutable de solo lectura para inspeccionar las pistas de auditoría del sistema.
    """

    queryset = AuditLog.objects.select_related("actor", "content_type").all()
    filterset_class = AuditLogFilter
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    search_fields = [
        "object_repr",
        "object_pk",
        "changes_text",
        "actor__full_name",
        "actor__email",
    ]
    ordering_fields = ["timestamp", "action", "id"]
    ordering = ["-timestamp"]
    pagination_class = CustomPageNumberPagination

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AuditLogDetailSerializer
        return AuditLogListSerializer

    @extend_schema(
        tags=["Auditoría"],
        summary="Listar recursos y tablas auditadas",
        description="Retorna el catálogo de tablas y modelos de la base de datos monitoreados por la auditoría.",
        responses={200: AuditResourceSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="resources")
    def resources(self, request):
        data = []
        for model in sorted(auditlog._registry.keys(), key=lambda m: m._meta.model_name):
            try:
                ct = ContentType.objects.get_for_model(model)
                data.append({
                    "resource": model._meta.model_name,
                    "label": str(model._meta.verbose_name),
                    "app": model._meta.app_label,
                    "content_type_id": ct.id,
                })
            except Exception:
                continue
        return Response(data)

    @extend_schema(
        tags=["Auditoría"],
        summary="Listar tipos de acciones de auditoría",
        description="Retorna los tipos de acciones disponibles en el registro (0=Creación, 1=Actualización, 2=Eliminación).",
        responses={200: AuditActionSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="actions")
    def actions(self, request):
        data = [
            {"action": 0, "name": "create", "label": "Creación"},
            {"action": 1, "name": "update", "label": "Actualización"},
            {"action": 2, "name": "delete", "label": "Eliminación"},
            {"action": 3, "name": "access", "label": "Acceso"},
        ]
        return Response(data)
