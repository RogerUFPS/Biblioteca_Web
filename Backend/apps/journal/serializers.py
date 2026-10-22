from django.db import transaction
from django.db.models import Prefetch
from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from apps.catalog.models import (
    AcademicProgram,
    Country,
    KnowledgeArea,
    Language,
    MaterialType,
    SharedAcademicProgramKnowledgeArea,
)
from apps.core.serializers import (
    RelationConfig,
    SoftDeleteRelationSyncMixin,
)
from apps.core.viewsets import ArchivedNameMixin
from apps.platforms import services as platform_services
from apps.platforms.models import LinkCheckLog, Platform

from . import models
from .services import (
    validate_platform_for_journal_association,
)


JOURNAL_RELATION_CONFIG = (
    RelationConfig(
        data_field="languages",
        through_model=models.SharedJournalLanguage,
        relation_field="language",
    ),
    RelationConfig(
        data_field="countries",
        through_model=models.SharedJournalCountry,
        relation_field="country",
    ),
    RelationConfig(
        data_field="material_types",
        through_model=models.SharedJournalMaterialType,
        relation_field="material_type",
    ),
    RelationConfig(
        data_field="academic_programs",
        through_model=models.SharedJournalAcademicProgram,
        relation_field="academic_program",
    ),
    RelationConfig(
        data_field="platforms",
        through_model=models.SharedJournalPlatform,
        relation_field="platform",
        extra_fields=(
            "start_period",
            "finish_period",
            "has_full_text",
        ),
        ordering=("platform__name",),
    ),
)


def _journal_platform_links(instance, *, published_only=False):
    prefetched = getattr(instance, "_url_platform_links", None)
    if prefetched is not None:
        if not published_only:
            return prefetched
        return [
            link for link in prefetched
            if link.platform.status == Platform.Status.PUBLICADO
        ]

    queryset = (
        models.SharedJournalPlatform.objects
        .filter(journal=instance, platform__deleted_at__isnull=True)
        .select_related("platform")
        .prefetch_related(
            Prefetch(
                "platform__link_check_logs",
                queryset=(
                    LinkCheckLog.objects
                    .filter(journal_platform__isnull=True)
                    .order_by(*platform_services.LINK_LOG_ORDERING)
                ),
                to_attr="_public_link_logs",
            ),
            Prefetch(
                "link_check_logs",
                queryset=LinkCheckLog.objects.order_by(
                    *platform_services.LINK_LOG_ORDERING
                ),
                to_attr="_journal_link_logs",
            ),
        )
    )
    if published_only:
        queryset = queryset.filter(platform__status=Platform.Status.PUBLICADO)
    return queryset.order_by("platform__name")


def _represent_journal_platform(link, *, include_relation_key=False):
    public_log = platform_services.latest_platform_link_log(link.platform)
    journal_log = platform_services.latest_journal_link_log(link)
    data = {
        "id": link.platform_id,
        "name": link.platform.name,
        "public_url": public_log.url if public_log else None,
        "journal_url": journal_log.url if journal_log else None,
        "start_period": link.start_period,
        "finish_period": link.finish_period,
        "has_full_text": link.has_full_text,
    }
    if include_relation_key:
        data["platform"] = link.platform_id
        data["relation_id"] = link.pk
        data["status"] = link.platform.status
        data["is_public"] = link.platform.status == Platform.Status.PUBLICADO
        data["is_current"] = not link.is_deleted and link.finish_period is None
    return data


AUDIT_FIELDS = (
    "id",
    "created_by",
    "created_at",
    "updated_by",
    "updated_at",
    "deleted_by",
    "deleted_at",
    "delete_explanation",
)


class LicenseSerializer(ArchivedNameMixin, serializers.ModelSerializer):
    archived_unique_fields = ("name",)

    class Meta:
        model = models.License
        fields = [*AUDIT_FIELDS, "name"]
        read_only_fields = AUDIT_FIELDS


class JournalLicenseSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class JournalPublishSerializer(serializers.Serializer):
    licenses = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=models.License.objects.all(),
        required=False,
    )


def _normalize_issn(value: str) -> str:
    """
    Normaliza el ISSN al formato XXXX-XXXX.

    Admite como entrada el ISSN con o sin guion.
    """

    if not value or not value.strip():
        raise serializers.ValidationError(
            "El ISSN es obligatorio."
        )

    compact_issn = (
        "".join(value.split())
        .replace("-", "")
        .upper()
    )

    if (
        len(compact_issn) != 8
        or not compact_issn[:7].isdigit()
        or not (
            compact_issn[7].isdigit()
            or compact_issn[7] == "X"
        )
    ):
        raise serializers.ValidationError(
            "El ISSN debe tener el formato XXXX-XXXX."
        )

    return (
        f"{compact_issn[:4]}-"
        f"{compact_issn[4:]}"
    )


class JournalPlatformRelationSerializer(
    serializers.Serializer
):
    """
    Datos específicos de la relación entre una revista
    y una plataforma.
    """

    platform = serializers.PrimaryKeyRelatedField(
        queryset=Platform.objects.all(),
    )

    start_period = serializers.DateField(
        allow_null=True,
        read_only=True,
        help_text=(
            "Fecha de vinculación con la plataforma. "
            "Es administrada automáticamente por el sistema."
        ),
    )

    finish_period = serializers.DateField(
        allow_null=True,
        read_only=True,
        help_text=(
            "Fecha de finalización de la vinculación. "
            "Es administrada automáticamente por el sistema."
        ),
    )

    has_full_text = serializers.BooleanField(
        required=False,
    )

    public_url = serializers.URLField(read_only=True, allow_null=True)
    journal_url = serializers.URLField(
        required=False,
        allow_null=True,
        help_text=(
            "URL pública de la revista dentro de esta plataforma. "
            "Se conserva en LinkCheckLog."
        ),
    )

    def validate_journal_url(self, value):
        platform_services.validate_safe_http_url(
            value,
            field_name="journal_url",
        )
        return value

    def to_internal_value(self, data):
        managed_fields = {
            field: "Es administrado automáticamente por el sistema."
            for field in ("start_period", "finish_period")
            if field in data
        }
        if managed_fields:
            raise serializers.ValidationError(managed_fields)
        return super().to_internal_value(data)

    def validate(self, attrs):
        platform = attrs.get("platform")
        if platform:
            validate_platform_for_journal_association(
                platform,
                field_name="platform",
            )

        return attrs


class JournalKnowledgeAreaOriginSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_manual = serializers.BooleanField()
    is_derived = serializers.BooleanField()
    editable = serializers.BooleanField()


@extend_schema_field(JournalKnowledgeAreaOriginSerializer(many=True))
class JournalKnowledgeAreasField(serializers.Field):
    """Entrada por IDs y salida administrativa con procedencia."""

    def get_attribute(self, instance):
        return instance

    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError(
                "Se esperaba una lista de IDs de áreas de conocimiento."
            )
        if any(
            not isinstance(area_id, int) or isinstance(area_id, bool)
            for area_id in data
        ):
            raise serializers.ValidationError(
                "Cada área de conocimiento debe identificarse con un ID entero."
            )
        if len(data) != len(set(data)):
            raise serializers.ValidationError(
                "Un área de conocimiento no puede aparecer más de una vez."
            )
        areas = list(KnowledgeArea.objects.filter(pk__in=data))
        if len(areas) != len(data):
            raise serializers.ValidationError(
                "Una o más áreas de conocimiento no existen o no están vigentes."
            )
        by_id = {area.pk: area for area in areas}
        return [by_id[area_id] for area_id in data]

    def to_representation(self, journal):
        return [
            {
                "id": link.knowledge_area_id,
                "name": link.knowledge_area.name,
                "is_manual": link.is_manual,
                "is_derived": link.is_derived,
                "editable": link.editable,
            }
            for link in journal.knowledge_area_links.select_related(
                "knowledge_area"
            ).filter(knowledge_area__deleted_at__isnull=True).order_by(
                "knowledge_area__name"
            )
        ]


class JournalSerializer(
    SoftDeleteRelationSyncMixin,
    ArchivedNameMixin,
    serializers.ModelSerializer,
):
    """
    Serializador administrativo de revistas.

    La identificación y deduplicación se realiza mediante ISSN.

    Todas las relaciones mediante tablas intermedias se sincronizan
    mediante SoftDeleteRelationSyncMixin.

    La relación con plataformas utiliza el mismo mecanismo genérico,
    incluyendo sus atributos adicionales:
    start_period, finish_period y has_full_text.
    """

    archived_unique_fields = ("issn",)

    relation_config = JOURNAL_RELATION_CONFIG
    relation_parent_field = "journal"

    relation_delete_explanation = (
        "Relación eliminada durante "
        "la actualización de la revista."
    )

    languages = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Language.objects.all(),
        required=False,
        write_only=True,
    )

    countries = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Country.objects.all(),
        required=False,
        write_only=True,
    )

    knowledge_areas = JournalKnowledgeAreasField(
        required=False,
        help_text=(
            "Lista de IDs para la selección manual. La respuesta incluye "
            "procedencia y editabilidad de todas las áreas efectivas."
        ),
    )

    material_types = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=MaterialType.objects.all(),
        required=False,
        write_only=True,
    )

    academic_programs = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=AcademicProgram.objects.all(),
        required=False,
        write_only=True,
    )

    platforms = JournalPlatformRelationSerializer(
        many=True,
        required=False,
        write_only=True,
    )

    licenses = serializers.SerializerMethodField()

    class Meta:
        model = models.Journal

        fields = [
            *AUDIT_FIELDS,
            "issn",
            "title",
            "editorial",
            "licenses",
            "url_image",
            "has_apc",
            "active",
            "publication_date",
            "validated_by",
            "validated_at",
            "fetched_at",
            "languages",
            "countries",
            "knowledge_areas",
            "material_types",
            "academic_programs",
            "platforms",
        ]

        read_only_fields = [
            *AUDIT_FIELDS,
            "active",
            "validated_by",
            "validated_at",
            "fetched_at",
        ]

    def validate_issn(self, value):
        """
        Normaliza el ISSN para garantizar una representación
        consistente y permitir una deduplicación correcta.
        """
        return _normalize_issn(value)

    def validate(self, attrs):
        """
        Valida los datos generales de la revista.

        En actualizaciones parciales se utilizan los valores
        existentes cuando alguno de los períodos no fue enviado.

        Cuando se está restaurando automáticamente una revista
        archivada, también se consideran sus valores anteriores.
        """
        attrs = super().validate(attrs)

        base_instance = (
            self.instance
            or getattr(
                self,
                "_archived_instance",
                None,
            )
        )

        return attrs

    def validate_platforms(self, value):
        """
        Valida duplicados y evita asociar plataformas eliminadas.
        """
        platform_ids = [
            item["platform"].pk
            for item in value
        ]

        if len(platform_ids) != len(set(platform_ids)):
            raise serializers.ValidationError(
                "Una plataforma no puede aparecer más de una vez."
            )

        active_platform_ids = set()
        if self.instance is not None:
            active_platform_ids = set(
                models.SharedJournalPlatform.objects.filter(journal=self.instance)
                .values_list("platform_id", flat=True)
            )
        for item in value:
            platform = item["platform"]
            if platform.pk not in active_platform_ids:
                validate_platform_for_journal_association(
                    platform,
                    field_name="platform",
                )
            if platform.pk not in active_platform_ids and not item.get("journal_url"):
                raise serializers.ValidationError(
                    "Cada relación nueva requiere journal_url."
                )

        return value

    def _prepare_relation_data(self, validated_data):
        """
        Extrae las relaciones recibidas y deriva knowledge_areas cuando
        academic_programs fue enviado.

        Si academic_programs no viene en un PATCH, ninguna de las dos
        relaciones se modifica.
        """
        relation_data = self._extract_relation_data(validated_data)
        if "knowledge_areas" in validated_data:
            relation_data["knowledge_areas"] = validated_data.pop(
                "knowledge_areas"
            )
        return relation_data

    def to_representation(self, instance):
        representation = super().to_representation(instance)

        representation = self._represent_relations(
            instance=instance,
            representation=representation,
        )
        representation["platforms"] = [
            _represent_journal_platform(link, include_relation_key=True)
            for link in _journal_platform_links(instance)
        ]
        return representation

    @extend_schema_field(
        serializers.ListField(child=serializers.IntegerField())
    )
    def get_licenses(self, instance):
        return list(
            instance.license_links.order_by("license__name")
            .values_list("license_id", flat=True)
        )

    def _clear_validation(self, journal):
        """
        Una ficha modificada debe ser validada nuevamente
        antes de regresar a la consulta pública.
        """
        if (
            not journal.active
            and journal.validated_by_id is None
            and journal.validated_at is None
        ):
            return

        journal.active = False
        journal.validated_by = None
        journal.validated_at = None

        journal.save(
            update_fields=[
                "active",
                "validated_by",
                "validated_at",
            ]
        )

    def _sync_platform_urls(self, journal, platform_data):
        if not platform_data:
            return

        user = journal.updated_by or journal.created_by
        links_by_platform = {
            link.platform_id: link
            for link in models.SharedJournalPlatform.objects.filter(
                journal=journal,
                platform_id__in=[
                    item["platform"].pk
                    for item in platform_data
                    if item.get("journal_url") is not None
                ],
            ).select_related("platform")
        }

        for item in platform_data:
            if item.get("journal_url") is None:
                continue
            link = links_by_platform[item["platform"].pk]
            platform_services.register_link_url(
                platform=link.platform,
                journal_platform=link,
                url=item["journal_url"],
                user=user,
            )

    @transaction.atomic
    def create(self, validated_data):
        relation_data = self._prepare_relation_data(
            validated_data
        )

        # Crear o restaurar una revista nunca equivale a publicarla.
        validated_data["active"] = False
        validated_data["validated_by"] = None
        validated_data["validated_at"] = None

        journal = super().create(
            validated_data
        )

        was_archived = (
            getattr(
                self,
                "_archived_instance",
                None,
            )
            is not None
        )

        if was_archived:
            self._clear_validation(journal)

        if relation_data:
            self._sync_relations(
                parent=journal,
                relation_data=relation_data,
            )
            if "knowledge_areas" in relation_data:
                from .classification import sync_manual_knowledge_areas
                sync_manual_knowledge_areas(
                    journal,
                    relation_data["knowledge_areas"],
                    user=journal.created_by,
                )
            self._sync_platform_urls(
                journal,
                relation_data.get("platforms"),
            )

        from apps.platforms.classification import recalculate_platforms
        from .classification import recalculate_journals

        recalculate_journals(
            [journal.pk],
            user=journal.created_by,
            invalidate_on_change=False,
        )
        recalculate_platforms(
            {
                item["platform"].pk
                for item in relation_data.get("platforms", [])
            },
            user=journal.created_by,
        )

        return journal

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        previous_platform_ids = set(
            models.SharedJournalPlatform.objects.filter(journal=instance)
            .values_list("platform_id", flat=True)
        )
        relation_data = self._prepare_relation_data(
            validated_data
        )

        journal = super().update(
            instance,
            validated_data,
        )

        if relation_data:
            self._sync_relations(
                parent=journal,
                relation_data=relation_data,
            )
            if "knowledge_areas" in relation_data:
                from .classification import sync_manual_knowledge_areas
                sync_manual_knowledge_areas(
                    journal,
                    relation_data["knowledge_areas"],
                    user=journal.updated_by or journal.created_by,
                )
            self._sync_platform_urls(
                journal,
                relation_data.get("platforms"),
            )

        from apps.platforms.classification import recalculate_platforms
        from .classification import recalculate_journals

        user = journal.updated_by or journal.created_by
        recalculate_journals(
            [journal.pk],
            user=user,
            invalidate_on_change=False,
        )
        self._clear_validation(journal)

        current_platform_ids = set(
            models.SharedJournalPlatform.objects.filter(journal=journal)
            .values_list("platform_id", flat=True)
        )
        recalculate_platforms(
            previous_platform_ids | current_platform_ids,
            user=user,
        )

        return journal


# ==============================================================================
# ESQUEMAS DE RESPUESTA PÚBLICA PARA SWAGGER
# ==============================================================================


class JournalPublicLanguageSchemaSerializer(
    serializers.Serializer
):
    id = serializers.IntegerField()
    name = serializers.CharField()
    abbreviation = serializers.CharField()


class JournalPublicCountrySchemaSerializer(
    serializers.Serializer
):
    id = serializers.IntegerField()
    name = serializers.CharField()
    abbreviation = serializers.CharField()
    emoji_flag = serializers.CharField(
        allow_blank=True,
        allow_null=True,
    )


class JournalPublicKnowledgeAreaSchemaSerializer(
    serializers.Serializer
):
    id = serializers.IntegerField()
    name = serializers.CharField()


class JournalPublicMaterialTypeSchemaSerializer(
    serializers.Serializer
):
    id = serializers.IntegerField()
    name = serializers.CharField()


class JournalPublicAcademicProgramSchemaSerializer(
    serializers.Serializer
):
    id = serializers.IntegerField()
    name = serializers.CharField()


class JournalPublicPlatformSchemaSerializer(
    serializers.Serializer
):
    id = serializers.IntegerField()
    name = serializers.CharField()
    public_url = serializers.URLField(
        allow_null=True,
        read_only=True,
    )
    journal_url = serializers.URLField(
        allow_null=True,
        read_only=True,
    )
    start_period = serializers.DateField(
        allow_null=True,
        read_only=True,
    )
    finish_period = serializers.DateField(
        allow_null=True,
        read_only=True,
    )
    has_full_text = serializers.BooleanField()


class JournalPublicSerializer(
    serializers.ModelSerializer
):
    """
    Serializador de solo lectura para la exploración pública.

    No expone campos internos de auditoría ni validación.
    """

    editorial_name = serializers.CharField(
        source="editorial.name",
        read_only=True,
        default=None,
    )

    languages = (
        serializers.SerializerMethodField()
    )

    countries = (
        serializers.SerializerMethodField()
    )

    knowledge_areas = (
        serializers.SerializerMethodField()
    )

    material_types = (
        serializers.SerializerMethodField()
    )

    academic_programs = (
        serializers.SerializerMethodField()
    )

    platforms = (
        serializers.SerializerMethodField()
    )
    licenses = serializers.SerializerMethodField()

    class Meta:
        model = models.Journal

        fields = [
            "id",
            "issn",
            "title",
            "editorial_name",
            "licenses",
            "url_image",
            "has_apc",
            "active",
            "publication_date",
            "languages",
            "countries",
            "knowledge_areas",
            "material_types",
            "academic_programs",
            "platforms",
        ]

    @extend_schema_field(JournalLicenseSerializer(many=True))
    def get_licenses(self, obj):
        return [
            {"id": link.license_id, "name": link.license.name}
            for link in obj.license_links.select_related("license")
            .order_by("license__name")
        ]

    @extend_schema_field(
        JournalPublicLanguageSchemaSerializer(many=True)
    )
    def get_languages(self, obj):
        return list(
            Language.objects.filter(
                journal_links__journal=obj,
                journal_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
                "abbreviation",
            )
        )

    @extend_schema_field(
        JournalPublicCountrySchemaSerializer(many=True)
    )
    def get_countries(self, obj):
        return list(
            Country.objects.filter(
                journal_links__journal=obj,
                journal_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
                "abbreviation",
                "emoji_flag",
            )
        )

    @extend_schema_field(
        JournalPublicKnowledgeAreaSchemaSerializer(many=True)
    )
    def get_knowledge_areas(self, obj):
        return list(
            KnowledgeArea.objects.filter(
                journal_links__journal=obj,
                journal_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
            )
        )

    @extend_schema_field(
        JournalPublicMaterialTypeSchemaSerializer(many=True)
    )
    def get_material_types(self, obj):
        return list(
            MaterialType.objects.filter(
                journal_links__journal=obj,
                journal_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
            )
        )

    @extend_schema_field(
        JournalPublicAcademicProgramSchemaSerializer(many=True)
    )
    def get_academic_programs(self, obj):
        return list(
            AcademicProgram.objects.filter(
                journal_links__journal=obj,
                journal_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
            )
        )

    @extend_schema_field(
        JournalPublicPlatformSchemaSerializer(many=True)
    )
    def get_platforms(self, obj):
        return [
            _represent_journal_platform(link)
            for link in _journal_platform_links(obj, published_only=True)
        ]
