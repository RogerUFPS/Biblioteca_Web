import django_filters  # type: ignore[import-untyped]

from django.db.models import Q

from apps.platforms.models import Platform

from . import models


class JournalBaseFilter(django_filters.FilterSet):
    """
    Filtros disponibles para la exploración pública de revistas.

    Las relaciones intermedias tienen en cuenta Soft Delete,
    evitando utilizar asociaciones o catálogos eliminados.
    """

    issn = django_filters.CharFilter(
        method="filter_issn",
    )

    title = django_filters.CharFilter(
        field_name="title",
        lookup_expr="icontains",
    )

    editorial = django_filters.NumberFilter(
        method="filter_editorial",
    )

    language = django_filters.NumberFilter(
        method="filter_language",
    )

    country = django_filters.NumberFilter(
        method="filter_country",
    )

    knowledge_area = django_filters.NumberFilter(
        method="filter_knowledge_area",
    )

    material_type = django_filters.NumberFilter(
        method="filter_material_type",
    )

    academic_program = django_filters.NumberFilter(
        method="filter_academic_program",
    )

    platform = django_filters.NumberFilter(
        method="filter_platform",
    )

    license = django_filters.NumberFilter(
        method="filter_license",
    )

    has_apc = django_filters.BooleanFilter(
        field_name="has_apc",
    )

    publication_date_from = django_filters.DateFilter(
        field_name="publication_date",
        lookup_expr="gte",
    )

    publication_date_to = django_filters.DateFilter(
        field_name="publication_date",
        lookup_expr="lte",
    )

    published_platforms_only = False

    class Meta:
        model = models.Journal
        fields = []

    def filter_issn(self, queryset, name, value):
        """
        Permite consultar el ISSN con o sin guion.

        Ejemplos:
        1234-5678
        12345678
        """

        normalized = (
            "".join(value.split())
            .replace("-", "")
            .upper()
        )

        if len(normalized) == 8:
            normalized = (
                f"{normalized[:4]}-"
                f"{normalized[4:]}"
            )

        return queryset.filter(
            issn__iexact=normalized,
        )

    def filter_editorial(self, queryset, name, value):
        return queryset.filter(
            editorial_id=value,
            editorial__deleted_at__isnull=True,
        )

    def filter_language(self, queryset, name, value):
        return queryset.filter(
            language_links__language_id=value,
            language_links__deleted_at__isnull=True,
            language_links__language__deleted_at__isnull=True,
        ).distinct()

    def filter_country(self, queryset, name, value):
        return queryset.filter(
            country_links__country_id=value,
            country_links__deleted_at__isnull=True,
            country_links__country__deleted_at__isnull=True,
        ).distinct()

    def filter_knowledge_area(self, queryset, name, value):
        return queryset.filter(
            Q(knowledge_area_links__is_manual=True)
            | Q(knowledge_area_links__is_derived=True),
            knowledge_area_links__knowledge_area_id=value,
            knowledge_area_links__deleted_at__isnull=True,
            knowledge_area_links__knowledge_area__deleted_at__isnull=True,
        ).distinct()

    def filter_material_type(self, queryset, name, value):
        return queryset.filter(
            material_type_links__material_type_id=value,
            material_type_links__deleted_at__isnull=True,
            material_type_links__material_type__deleted_at__isnull=True,
        ).distinct()

    def filter_academic_program(self, queryset, name, value):
        return queryset.filter(
            academic_program_links__academic_program_id=value,
            academic_program_links__deleted_at__isnull=True,
            academic_program_links__academic_program__deleted_at__isnull=True,
        ).distinct()

    def filter_platform(self, queryset, name, value):
        filters = {
            "platform_links__platform_id": value,
            "platform_links__deleted_at__isnull": True,
            "platform_links__platform__deleted_at__isnull": True,
        }
        if self.published_platforms_only:
            filters["platform_links__platform__status"] = (
                Platform.Status.PUBLICADO
            )

        return queryset.filter(**filters).distinct()

    def filter_license(self, queryset, name, value):
        return queryset.filter(
            license_links__license_id=value,
            license_links__deleted_at__isnull=True,
            license_links__license__deleted_at__isnull=True,
        ).distinct()


class JournalFilter(JournalBaseFilter):
    """Filtros del listado administrativo de revistas."""

    active = django_filters.BooleanFilter()

    class Meta:
        model = models.Journal
        fields = []


class JournalPublicFilter(JournalBaseFilter):
    """Filtros de la exploración pública de revistas publicadas."""

    published_platforms_only = True

    class Meta:
        model = models.Journal
        fields = []
