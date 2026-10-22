from django.db import transaction
from rest_framework import serializers

from apps.core.viewsets import ArchivedNameMixin
from apps.core.relations import sync_auditable_relation_ids

from . import models

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


class InstitutionSerializer(ArchivedNameMixin, serializers.ModelSerializer):
    archived_unique_fields = ("name",)

    class Meta:
        model = models.Institution
        fields = [*AUDIT_FIELDS, "name"]
        read_only_fields = AUDIT_FIELDS


class LanguageSerializer(ArchivedNameMixin, serializers.ModelSerializer):
    archived_unique_fields = ("name", "abbreviation")

    class Meta:
        model = models.Language
        fields = [*AUDIT_FIELDS, "abbreviation", "name"]
        read_only_fields = AUDIT_FIELDS


class CountrySerializer(ArchivedNameMixin, serializers.ModelSerializer):
    archived_unique_fields = ("name", "abbreviation")

    class Meta:
        model = models.Country
        fields = [*AUDIT_FIELDS, "name", "abbreviation", "emoji_flag"]
        read_only_fields = AUDIT_FIELDS


class MaterialTypeSerializer(ArchivedNameMixin, serializers.ModelSerializer):
    archived_unique_fields = ("name",)

    class Meta:
        model = models.MaterialType
        fields = [*AUDIT_FIELDS, "name"]
        read_only_fields = AUDIT_FIELDS


class EditorialSerializer(ArchivedNameMixin, serializers.ModelSerializer):
    archived_unique_fields = ("name",)

    class Meta:
        model = models.Editorial
        fields = [*AUDIT_FIELDS, "name"]
        read_only_fields = AUDIT_FIELDS


class KnowledgeAreaSerializer(ArchivedNameMixin, serializers.ModelSerializer):
    archived_unique_fields = ("name",)

    class Meta:
        model = models.KnowledgeArea
        fields = [*AUDIT_FIELDS, "name"]
        read_only_fields = AUDIT_FIELDS


class AcademicProgramSerializer(ArchivedNameMixin, serializers.ModelSerializer):
    archived_unique_fields = ("name",)
    knowledge_areas = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=models.KnowledgeArea.objects.all(),
        required=True,
        write_only=True,
    )
    confirm_empty_knowledge_areas = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
        help_text=(
            "Confirmación explícita requerida para dejar el programa sin "
            "áreas; puede reclasificar revistas y plataformas relacionadas."
        ),
    )

    class Meta:
        model = models.AcademicProgram
        fields = [
            *AUDIT_FIELDS,
            "name",
            "knowledge_areas",
            "confirm_empty_knowledge_areas",
        ]
        read_only_fields = AUDIT_FIELDS

    def validate_knowledge_areas(self, value):
        if len({area.pk for area in value}) != len(value):
            raise serializers.ValidationError(
                "No se puede repetir un área de conocimiento."
            )
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if (
            "knowledge_areas" in attrs
            and not attrs["knowledge_areas"]
            and not attrs.get("confirm_empty_knowledge_areas", False)
        ):
            raise serializers.ValidationError({
                "confirm_empty_knowledge_areas": (
                    "El programa quedará sin áreas del conocimiento. Esto puede "
                    "cambiar la clasificación de revistas y plataformas "
                    "relacionadas; confirme explícitamente enviando true."
                )
            })
        return attrs

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["knowledge_areas"] = list(
            instance.knowledge_area_links.filter(
                knowledge_area__deleted_at__isnull=True,
            ).values_list("knowledge_area_id", flat=True)
        )
        return representation

    @transaction.atomic
    def create(self, validated_data):
        knowledge_areas = validated_data.pop("knowledge_areas")
        validated_data.pop("confirm_empty_knowledge_areas", None)
        program = super().create(validated_data)
        sync_auditable_relation_ids(
            through_model=models.SharedAcademicProgramKnowledgeArea,
            parent_field="academic_program",
            parent_id=program.pk,
            related_field="knowledge_area",
            desired_ids=(area.pk for area in knowledge_areas),
            user=program.created_by,
            delete_explanation="Relación programa-área retirada durante la actualización.",
        )
        return program

    @transaction.atomic
    def update(self, instance, validated_data):
        knowledge_areas = validated_data.pop("knowledge_areas", None)
        validated_data.pop("confirm_empty_knowledge_areas", None)
        program = super().update(instance, validated_data)
        if knowledge_areas is not None:
            user = program.updated_by or program.created_by
            changed = sync_auditable_relation_ids(
                through_model=models.SharedAcademicProgramKnowledgeArea,
                parent_field="academic_program",
                parent_id=program.pk,
                related_field="knowledge_area",
                desired_ids=(area.pk for area in knowledge_areas),
                user=user,
                delete_explanation=(
                    "Relación programa-área retirada durante la actualización."
                ),
            )
            if changed:
                from apps.journal.classification import propagate_catalog_change
                propagate_catalog_change([program.pk], user=user)
        return program
