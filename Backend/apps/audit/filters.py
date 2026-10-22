import django_filters
from auditlog.models import LogEntry
from .models import AuditLog


class AuditLogFilter(django_filters.FilterSet):
    """Filtros avanzados para consultar registros de auditoría."""

    action = django_filters.NumberFilter(
        field_name="action",
        help_text="Código numérico de acción (0=create, 1=update, 2=delete, 3=access).",
    )
    action_name = django_filters.CharFilter(
        method="filter_action_name",
        help_text="Nombre textual de la acción ('create', 'update', 'delete', 'access').",
    )
    resource = django_filters.CharFilter(
        method="filter_resource",
        help_text="Nombre del modelo/tabla auditada (ej. 'platform', 'journal', 'institution').",
    )
    content_type = django_filters.NumberFilter(
        field_name="content_type_id",
        help_text="ID del ContentType correspondiente al recurso.",
    )
    object_id = django_filters.CharFilter(
        field_name="object_pk",
        help_text="Identificador único (PK) del objeto afectado.",
    )
    actor = django_filters.NumberFilter(
        field_name="actor_id",
        help_text="ID del usuario que ejecutó el cambio (o null si fue anónimo).",
    )
    is_anonymous = django_filters.BooleanFilter(
        method="filter_is_anonymous",
        help_text="Filtrar por cambios realizados sin usuario autenticado (true o false).",
    )
    from_date = django_filters.IsoDateTimeFilter(
        field_name="timestamp",
        lookup_expr="gte",
        help_text="Fecha y hora inicial en formato ISO-8601 (ej. '2026-10-01T00:00:00Z').",
    )
    to_date = django_filters.IsoDateTimeFilter(
        field_name="timestamp",
        lookup_expr="lte",
        help_text="Fecha y hora final en formato ISO-8601 (ej. '2026-10-31T23:59:59Z').",
    )

    class Meta:
        model = AuditLog
        fields = [
            "action",
            "action_name",
            "resource",
            "content_type",
            "object_id",
            "actor",
            "is_anonymous",
            "from_date",
            "to_date",
        ]

    def filter_action_name(self, queryset, name, value):
        if not value:
            return queryset
        action_map = {
            "create": LogEntry.Action.CREATE,
            "update": LogEntry.Action.UPDATE,
            "delete": LogEntry.Action.DELETE,
            "access": LogEntry.Action.ACCESS,
        }
        mapped_action = action_map.get(value.lower().strip())
        if mapped_action is not None:
            return queryset.filter(action=mapped_action)
        return queryset.none()

    def filter_resource(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(content_type__model__iexact=value.strip())

    def filter_is_anonymous(self, queryset, name, value):
        if value is True:
            return queryset.filter(actor__isnull=True)
        elif value is False:
            return queryset.filter(actor__isnull=False)
        return queryset
