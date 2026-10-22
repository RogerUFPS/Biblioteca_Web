import django_filters
from . import models


class ScheduleFilter(django_filters.FilterSet):
    """
    Filtro avanzado para programaciones de cosecha.
    """

    platform = django_filters.NumberFilter(
        field_name="platforms__id",
        help_text="ID de una plataforma asociada a la programación.",
    )
    frequency = django_filters.CharFilter(
        field_name="frequency",
        lookup_expr="iexact",
        help_text="Frecuencia (once, daily, weekly, monthly).",
    )
    start_date_after = django_filters.DateTimeFilter(
        field_name="start_date",
        lookup_expr="gte",
        help_text="Primera fecha programada, posterior o igual a (ISO-8601).",
    )
    start_date_before = django_filters.DateTimeFilter(
        field_name="start_date",
        lookup_expr="lte",
        help_text="Primera fecha programada, anterior o igual a (ISO-8601).",
    )

    class Meta:
        model = models.Schedule
        fields = [
            "platform",
            "frequency",
            "start_date_after",
            "start_date_before",
        ]


class HarvestFilter(django_filters.FilterSet):
    """
    Filtro avanzado para ejecuciones de cosecha.
    """

    platform = django_filters.NumberFilter(
        field_name="platform_id",
        help_text="ID de la plataforma cosechada.",
    )
    schedule = django_filters.NumberFilter(
        field_name="schedule_id",
        help_text="ID de la programación asociada.",
    )
    state = django_filters.CharFilter(
        field_name="state",
        lookup_expr="iexact",
        help_text="Estado de la cosecha (pending, running, completed, failed, cancelled, paused).",
    )
    created_at_after = django_filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="gte",
        help_text="Fecha de creación posterior o igual a (ISO-8601).",
    )
    created_at_before = django_filters.DateTimeFilter(
        field_name="created_at",
        lookup_expr="lte",
        help_text="Fecha de creación anterior o igual a (ISO-8601).",
    )
    started_at_after = django_filters.DateTimeFilter(
        field_name="started_at",
        lookup_expr="gte",
        help_text="Fecha de inicio posterior o igual a (ISO-8601).",
    )
    started_at_before = django_filters.DateTimeFilter(
        field_name="started_at",
        lookup_expr="lte",
        help_text="Fecha de inicio anterior o igual a (ISO-8601).",
    )
    finished_at_after = django_filters.DateTimeFilter(
        field_name="finished_at",
        lookup_expr="gte",
        help_text="Fecha de fin posterior o igual a (ISO-8601).",
    )
    finished_at_before = django_filters.DateTimeFilter(
        field_name="finished_at",
        lookup_expr="lte",
        help_text="Fecha de fin anterior o igual a (ISO-8601).",
    )

    class Meta:
        model = models.Harvest
        fields = [
            "platform",
            "schedule",
            "state",
            "created_at_after",
            "created_at_before",
            "started_at_after",
            "started_at_before",
            "finished_at_after",
            "finished_at_before",
        ]
