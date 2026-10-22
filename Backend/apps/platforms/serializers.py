from django.db import transaction
from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from apps.catalog.models import (
    AcademicProgram,
    Country,
    Institution,
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

from . import classification, models, services


PLATFORM_RELATION_CONFIG = (
    RelationConfig(
        data_field="institutions",
        through_model=models.SharedPlatformSupport,
        relation_field="institution",
    ),
    RelationConfig(
        data_field="languages",
        through_model=models.SharedPlatformLanguage,
        relation_field="language",
    ),
    RelationConfig(
        data_field="countries",
        through_model=models.SharedPlatformCountry,
        relation_field="country",
    ),
    RelationConfig(
        data_field="knowledge_areas",
        through_model=models.SharedPlatformKnowledgeArea,
        relation_field="knowledge_area",
    ),
    RelationConfig(
        data_field="material_types",
        through_model=models.SharedPlatformMaterialType,
        relation_field="material_type",
    ),
    RelationConfig(
        data_field="academic_programs",
        through_model=models.SharedPlatformAcademicProgram,
        relation_field="academic_program",
    ),
)


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


VALID_SINTAXIS_FIELD_KEYS = (
    "title",
    "author",
    "subject",
    "issn",
    "language",
    "year",
)


"""
Plantilla inmutable para el campo ``fields`` de ValidSintaxis.

Las claves canónicas permitidas se mantienen en una tupla inmutable.
El valor almacenado en ``fields`` contiene el prefijo/parámetro que
la plataforma utiliza para cada campo.

Ejemplo::

    {
        "title":    "ti",
        "author":   "au",
        "subject":  "su",
        "issn":     "is",
        "language": "la",
        "year":     "yr"
    }
"""


class ValidSintaxisSerializer(
    ArchivedNameMixin,
    serializers.ModelSerializer,
):
    archived_unique_fields = ("name",)

    fields_template = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "Plantilla de referencia para construir el campo ``fields``. "
            "Muestra las claves canónicas admitidas con sus valores vacíos."
        ),
    )

    class Meta:
        model = models.ValidSintaxis

        fields = [
            *AUDIT_FIELDS,
            "name",
            "booleans",
            "parenthesis",
            "fields",
            "fields_template",
        ]

        read_only_fields = [
            *AUDIT_FIELDS,
            "fields_template",
        ]

        extra_kwargs = {
            "fields": {
                "help_text": (
                    "Mapeo de campos semánticos a prefijos de la API. "
                    "Use ``fields_template`` como referencia de las claves disponibles. "
                    "Ejemplo: {\"title\": \"ti\", \"author\": \"au\", \"issn\": \"is\"}"
                ),
            }
        }

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_fields_template(self, obj):
        return {key: "" for key in VALID_SINTAXIS_FIELD_KEYS}

    def validate_fields(self, value):
        """
        Valida que el campo ``fields`` sea un diccionario plano
        de strings y que sus claves sean un subconjunto de la
        plantilla canónica.
        """
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "El campo debe ser un objeto JSON (diccionario)."
            )

        allowed_keys = set(VALID_SINTAXIS_FIELD_KEYS)
        invalid_keys = set(value.keys()) - allowed_keys

        if invalid_keys:
            raise serializers.ValidationError(
                f"Las siguientes claves no están permitidas: "
                f"{sorted(invalid_keys)}. "
                f"Claves válidas: {sorted(allowed_keys)}."
            )

        for key, val in value.items():
            if not isinstance(val, str):
                raise serializers.ValidationError(
                    f"El valor de la clave '{key}' debe ser una cadena de texto."
                )

        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        configuration = services.normalized_syntax_configuration(
            {
                "booleans": attrs.get("booleans", getattr(self.instance, "booleans", [])),
                "parenthesis": attrs.get(
                    "parenthesis", getattr(self.instance, "parenthesis", False)
                ),
                "fields": attrs.get("fields", getattr(self.instance, "fields", {})),
            }
        )
        duplicate = services.find_identical_syntax(
            configuration,
            exclude_id=getattr(self.instance, "pk", None),
        )
        if duplicate:
            raise serializers.ValidationError({
                "detail": "Ya existe una sintaxis con esta configuración.",
                "existing_id": duplicate.pk,
            })
        return attrs


class ValidSintaxisSimilarityRequestSerializer(serializers.Serializer):
    booleans = serializers.ListField(child=serializers.CharField())
    parenthesis = serializers.BooleanField()
    fields = serializers.DictField(child=serializers.CharField())

    def validate_fields(self, value):
        return ValidSintaxisSerializer().validate_fields(value)


class ValidSintaxisSimilarityResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    similarity = serializers.IntegerField()
    matching_fields = serializers.ListField(child=serializers.CharField())
    different_fields = serializers.ListField(child=serializers.CharField())


class ValidSintaxisPublicSerializer(
    serializers.ModelSerializer,
):
    class Meta:
        model = models.ValidSintaxis

        fields = [
            "name",
            "booleans",
            "parenthesis",
            "fields",
        ]


class LinkCheckLogSerializer(
    serializers.ModelSerializer,
):
    verification_status = serializers.SerializerMethodField(
        help_text="unverified, available o unavailable según el último chequeo.",
    )

    class Meta:
        model = models.LinkCheckLog

        fields = [
            *AUDIT_FIELDS,
            "platform",
            "journal_platform",
            "url",
            "fail_count",
            "http_status_code",
            "is_active",
            "last_check",
            "verification_status",
        ]

        read_only_fields = AUDIT_FIELDS

    @extend_schema_field(serializers.ChoiceField(
        choices=("unverified", "available", "unavailable"),
    ))
    def get_verification_status(self, obj):
        return services.link_verification_status(obj)


class PlatformLinkCheckResultSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=("platform", "journal"))
    journal = serializers.IntegerField(allow_null=True)
    journal_platform = serializers.IntegerField(allow_null=True)
    url = serializers.URLField(allow_null=True)
    is_active = serializers.BooleanField()
    http_status_code = serializers.IntegerField(allow_null=True)
    last_check = serializers.DateTimeField(allow_null=True)
    verification_status = serializers.ChoiceField(
        choices=("unverified", "available", "unavailable"),
    )
    error = serializers.CharField(required=False)


class PlatformLinksCheckResponseSerializer(serializers.Serializer):
    platform = serializers.IntegerField()
    checked = serializers.IntegerField()
    available = serializers.IntegerField()
    failed = serializers.IntegerField()
    results = PlatformLinkCheckResultSerializer(many=True)


class PlatformSerializer(
    SoftDeleteRelationSyncMixin,
    ArchivedNameMixin,
    serializers.ModelSerializer,
):
    """
    Serializador administrativo de plataformas.

    Las relaciones mediante tablas intermedias se sincronizan
    mediante SoftDeleteRelationSyncMixin.

    La relación con áreas del conocimiento no se recibe directamente
    del cliente: se deriva automáticamente a partir de los programas
    académicos seleccionados y de SharedAcademicProgramKnowledgeArea.
    """

    archived_unique_fields = ("name",)

    relation_config = PLATFORM_RELATION_CONFIG
    relation_parent_field = "platform"

    relation_delete_explanation = (
        "Relación eliminada durante la actualización "
        "de la plataforma."
    )

    start_period = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Fecha de registro de la plataforma, administrada "
            "automáticamente por el sistema."
        ),
    )
    finish_period = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Fecha en que la plataforma fue marcada como obsoleta. "
            "Es administrada automáticamente por el sistema."
        ),
    )

    api_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Clave de API en texto plano; es opcional. "
            "Solo puede configurarse si existe base_api_url. "
            "Se almacenará cifrada."
        ),
    )

    public_url = serializers.URLField(
        required=False,
        allow_null=True,
        help_text=(
            "URL pública navegable. Se almacena como un nuevo "
            "LinkCheckLog general y no corresponde a base_api_url."
        )
    )

    base_api_url = serializers.URLField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "URL base de la API utilizada para cosecha automatizada. "
            "Es opcional cuando la plataforma solo se registra como referencia. "
            "Si se configura una API Key, esta URL es obligatoria."
        ),
    )

    institutions = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Institution.objects.all(),
        required=False,
        write_only=True,
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

    knowledge_areas = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=KnowledgeArea.objects.all(),
        required=False,
        write_only=True,
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

    class Meta:
        model = models.Platform

        fields = [
            *AUDIT_FIELDS,
            "name",
            "status",
            "base_api_url",
            "is_harvestable",
            "public_url",
            "api_key",
            "url_image",
            "start_period",
            "finish_period",
            "requires_registration",
            "has_access_text",
            "validated_by",
            "validated_at",
            "valid_sintaxis",
            "institutions",
            "languages",
            "countries",
            "knowledge_areas",
            "material_types",
            "academic_programs",
        ]
        read_only_fields = [
            *AUDIT_FIELDS,
            "status",
            "start_period",
            "finish_period",
            "validated_by",
            "validated_at",
        ]

    def to_internal_value(self, data):
        managed_fields = {
            field: "Es administrado automáticamente por el sistema."
            for field in ("start_period", "finish_period")
            if field in data
        }
        if managed_fields:
            raise serializers.ValidationError(managed_fields)
        return super().to_internal_value(data)

    def validate_public_url(self, value):
        services.validate_safe_http_url(value, field_name="public_url")
        return value

    def validate_base_api_url(self, value):
        """Normaliza una URL base vacía a ``None``."""
        if value == "":
            return None

        return value

    def validate_api_key(self, value):
        """Normaliza una API Key vacía a ``None``."""
        if value == "":
            return None

        return value

    def validate(self, attrs):
        """
        Valida las reglas de configuración de la cosecha.

        - Una plataforma puede existir sin API Key.
        - Una plataforma puede existir sin base_api_url si solo funciona
        como referencia pública.
        - Nunca se permite conservar/configurar una API Key sin una
        base_api_url correspondiente.
        - Las knowledge_areas se derivan automáticamente de los
        academic_programs.
        """
        attrs = super().validate(attrs)

        if self.instance is None and not attrs.get("public_url"):
            raise serializers.ValidationError({
                "public_url": "La URL pública es obligatoria al crear una plataforma."
            })

        instance = self.instance

        if "base_api_url" in attrs:
            effective_base_api_url = attrs["base_api_url"]
        elif instance is not None:
            effective_base_api_url = instance.base_api_url
        else:
            effective_base_api_url = None

        if "api_key" in attrs:
            effective_api_key = attrs["api_key"]
            has_api_key = bool(effective_api_key)
        elif instance is not None:
            has_api_key = bool(instance.encrypted_api_key)
        else:
            has_api_key = False

        effective_is_harvestable = attrs.get(
            "is_harvestable",
            instance.is_harvestable if instance is not None else False,
        )
        disabling_harvesting = (
            instance is not None
            and instance.is_harvestable
            and attrs.get("is_harvestable") is False
        )

        if effective_is_harvestable and not effective_base_api_url:
            raise serializers.ValidationError(
                {
                    "base_api_url": (
                        "Una plataforma cosechable debe tener una URL base "
                        "de la API (base_api_url)."
                    )
                }
            )

        if has_api_key and not effective_base_api_url:
            raise serializers.ValidationError({
                "base_api_url": (
                    "No se puede configurar una API Key sin una URL base "
                    "de la API (base_api_url)."
                )
            })

        if not effective_is_harvestable:
            explicitly_sent_base = bool(attrs.get("base_api_url"))
            explicitly_sent_key = "api_key" in attrs and bool(attrs["api_key"])
            inherited_configuration = (
                bool(effective_base_api_url) or has_api_key
            )
            if explicitly_sent_base or explicitly_sent_key or (
                inherited_configuration and not disabling_harvesting
            ):
                raise serializers.ValidationError({
                    "is_harvestable": (
                        "Una plataforma no cosechable no puede tener "
                        "base_api_url ni api_key."
                    )
                })

        return attrs

    def _prepare_relation_data(self, validated_data):
        """
        Extrae las relaciones recibidas y deriva las knowledge_areas
        cuando el cliente ha enviado academic_programs.

        Si academic_programs no fue enviado, las relaciones existentes
        no se modifican.
        """
        return self._extract_relation_data(validated_data)

    def to_representation(self, instance):
        representation = super().to_representation(
            instance
        )

        for data_field, through_model, relation_field in classification.MANUAL_SECTION_SPECS:
            links = through_model.objects.filter(
                platform=instance,
            ).select_related(relation_field).order_by(f"{relation_field}__name")
            representation[data_field] = [
                {
                    "id": getattr(link, f"{relation_field}_id"),
                    "name": getattr(link, relation_field).name,
                    "is_manual": link.is_manual,
                    "is_derived": link.is_derived,
                    "editable": link.is_manual and not link.is_derived,
                }
                for link in links
                if link.is_manual or link.is_derived
            ]
        latest_log = services.latest_platform_link_log(instance)
        representation["public_url"] = latest_log.url if latest_log else None
        return representation

    @transaction.atomic
    def create(self, validated_data):
        public_url = validated_data.pop("public_url", None)
        raw_api_key = validated_data.pop(
            "api_key",
            None,
        )

        relation_data = self._prepare_relation_data(
            validated_data
        )

        platform = super().create(
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
            platform.status = (
                models.Platform.Status.BORRADOR
            )

            platform.validated_by = None
            platform.validated_at = None

            platform.save(
                update_fields=[
                    "status",
                    "validated_by",
                    "validated_at",
                ]
            )

        if raw_api_key is not None:
            platform.set_api_key(
                raw_api_key
            )

            platform.save(
                update_fields=[
                    "encrypted_api_key",
                ]
            )

        if relation_data:
            classification.sync_manual_platform_sections(
                platform, relation_data, user=platform.created_by,
            )

        if public_url is not None:
            services.register_link_url(
                platform=platform,
                url=public_url,
                user=platform.created_by,
            )

        classification.recalculate_platforms([platform.pk], user=platform.created_by)

        return platform

    @transaction.atomic
    def update(
        self,
        instance,
        validated_data,
    ):
        public_url_was_sent = "public_url" in validated_data
        public_url = validated_data.pop("public_url", None)
        disabling_harvesting = validated_data.get("is_harvestable") is False
        api_key_was_sent = "api_key" in validated_data or disabling_harvesting

        raw_api_key = validated_data.pop(
            "api_key",
            None,
        )

        if disabling_harvesting:
            validated_data["base_api_url"] = None
            raw_api_key = None

        relation_data = self._prepare_relation_data(
            validated_data
        )

        platform = super().update(
            instance,
            validated_data,
        )

        if api_key_was_sent:
            platform.set_api_key(
                raw_api_key
            )

            platform.save(
                update_fields=[
                    "encrypted_api_key",
                ]
            )

        if relation_data:
            classification.sync_manual_platform_sections(
                platform,
                relation_data,
                user=platform.updated_by or platform.created_by,
            )

        if public_url_was_sent and public_url is not None:
            services.register_link_url(
                platform=platform,
                url=public_url,
                user=platform.updated_by or platform.created_by,
            )

        classification.recalculate_platforms(
            [platform.pk], user=platform.updated_by or platform.created_by,
        )

        return platform


# ==============================================================================
# ESQUEMAS DE RESPUESTA PÚBLICA PARA SWAGGER
# ==============================================================================


class PlatformPublicInstitutionSchemaSerializer(
    serializers.Serializer,
):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PlatformPublicLanguageSchemaSerializer(
    serializers.Serializer,
):
    id = serializers.IntegerField()
    name = serializers.CharField()
    abbreviation = serializers.CharField()


class PlatformPublicCountrySchemaSerializer(
    serializers.Serializer,
):
    id = serializers.IntegerField()
    name = serializers.CharField()
    abbreviation = serializers.CharField()
    emoji_flag = serializers.CharField(
        allow_blank=True,
        allow_null=True,
    )


class PlatformPublicKnowledgeAreaSchemaSerializer(
    serializers.Serializer,
):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PlatformPublicMaterialTypeSchemaSerializer(
    serializers.Serializer,
):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PlatformPublicAcademicProgramSchemaSerializer(
    serializers.Serializer,
):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PlatformPublicLinkStatusSchemaSerializer(
    serializers.Serializer,
):
    url = serializers.URLField(
        allow_null=True,
        help_text=(
            "URL pública de la plataforma registrada "
            "en el último chequeo."
        ),
    )

    is_active = serializers.BooleanField(
        allow_null=True,
    )

    last_check = serializers.DateTimeField(
        allow_null=True,
    )
    verification_status = serializers.ChoiceField(
        choices=("unverified", "available", "unavailable"),
        allow_null=True,
    )


class PlatformPublicSerializer(
    serializers.ModelSerializer,
):
    """
    Serializador de solo lectura para la exploración pública.

    No expone:

    - encrypted_api_key;
    - campos de auditoría interna;
    - datos internos de validación.
    """

    valid_sintaxis = ValidSintaxisPublicSerializer(
        read_only=True
    )

    institutions = serializers.SerializerMethodField()
    languages = serializers.SerializerMethodField()
    countries = serializers.SerializerMethodField()
    knowledge_areas = serializers.SerializerMethodField()
    material_types = serializers.SerializerMethodField()
    academic_programs = serializers.SerializerMethodField()
    link_status = serializers.SerializerMethodField()
    public_url = serializers.SerializerMethodField(
        help_text=(
            "URL pública navegable obtenida del último LinkCheckLog "
            "general no eliminado."
        )
    )

    class Meta:
        model = models.Platform

        fields = [
            "id",
            "name",
            "base_api_url",
            "is_harvestable",
            "public_url",
            "url_image",
            "start_period",
            "finish_period",
            "requires_registration",
            "has_access_text",
            "valid_sintaxis",
            "institutions",
            "languages",
            "countries",
            "knowledge_areas",
            "material_types",
            "academic_programs",
            "link_status",
        ]

    @extend_schema_field(
        PlatformPublicInstitutionSchemaSerializer(many=True)
    )
    def get_institutions(self, obj):
        return list(
            Institution.objects.filter(
                platform_support_links__platform=obj,
                platform_support_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
            )
        )

    @extend_schema_field(
        PlatformPublicLanguageSchemaSerializer(many=True)
    )
    def get_languages(self, obj):
        return list(
            Language.objects.filter(
                platform_links__platform=obj,
                platform_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
                "abbreviation",
            )
        )

    @extend_schema_field(
        PlatformPublicCountrySchemaSerializer(many=True)
    )
    def get_countries(self, obj):
        return list(
            Country.objects.filter(
                platform_links__platform=obj,
                platform_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
                "abbreviation",
                "emoji_flag",
            )
        )

    @extend_schema_field(
        PlatformPublicKnowledgeAreaSchemaSerializer(many=True)
    )
    def get_knowledge_areas(self, obj):
        return list(
            KnowledgeArea.objects.filter(
                platform_links__platform=obj,
                platform_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
            )
        )

    @extend_schema_field(
        PlatformPublicMaterialTypeSchemaSerializer(many=True)
    )
    def get_material_types(self, obj):
        return list(
            MaterialType.objects.filter(
                platform_links__platform=obj,
                platform_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
            )
        )

    @extend_schema_field(
        PlatformPublicAcademicProgramSchemaSerializer(many=True)
    )
    def get_academic_programs(self, obj):
        return list(
            AcademicProgram.objects.filter(
                platform_links__platform=obj,
                platform_links__deleted_at__isnull=True,
            ).values(
                "id",
                "name",
            )
        )

    @extend_schema_field(
        PlatformPublicLinkStatusSchemaSerializer
    )
    def get_link_status(self, obj):
        latest_log = services.latest_platform_link_log(obj)

        if latest_log:
            data = {
                "url": latest_log.url,
                "is_active": latest_log.is_active,
                "last_check": latest_log.last_check,
                "verification_status": services.link_verification_status(latest_log),
            }
        else:
            data = {
                "url": None,
                "is_active": None,
                "last_check": None,
                "verification_status": None,
            }

        return PlatformPublicLinkStatusSchemaSerializer(data).data

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_public_url(self, obj):
        latest_log = services.latest_platform_link_log(obj)
        return latest_log.url if latest_log else None
