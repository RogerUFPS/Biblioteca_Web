from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from apps.account.models import User
from .models import AuditLog


class AuditActorSerializer(serializers.ModelSerializer):
    """Información simplificada del usuario que realizó la acción."""

    class Meta:
        model = User
        fields = [
            "id",
            "code",
            "full_name",
            "email",
        ]
        read_only_fields = fields


class AuditLogListSerializer(serializers.ModelSerializer):
    """Serializador para listados paginados de registros de auditoría."""

    action_name = serializers.CharField(read_only=True)
    action_display = serializers.CharField(read_only=True)
    resource = serializers.CharField(read_only=True)
    resource_display = serializers.CharField(read_only=True)
    object_id = serializers.CharField(source="object_pk", read_only=True)
    actor_name = serializers.SerializerMethodField()
    is_soft_delete = serializers.BooleanField(read_only=True)
    is_restore = serializers.BooleanField(read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "timestamp",
            "action",
            "action_name",
            "action_display",
            "resource",
            "resource_display",
            "content_type",
            "object_id",
            "object_repr",
            "actor",
            "actor_name",
            "remote_addr",
            "is_soft_delete",
            "is_restore",
            "changes",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_actor_name(self, obj):
        if obj.actor:
            return getattr(obj.actor, "full_name", str(obj.actor))
        return None


class AuditLogDetailSerializer(AuditLogListSerializer):
    """Serializador detallado para consultar un registro de auditoría individual."""

    actor_detail = AuditActorSerializer(source="actor", read_only=True)

    class Meta(AuditLogListSerializer.Meta):
        fields = AuditLogListSerializer.Meta.fields + [
            "actor_detail",
            "additional_data",
            "changes_text",
        ]
        read_only_fields = fields


class AuditResourceSerializer(serializers.Serializer):
    """Esquema descriptivo de un recurso / tabla auditada en el sistema."""

    resource = serializers.CharField()
    label = serializers.CharField()
    app = serializers.CharField()
    content_type_id = serializers.IntegerField()


class AuditActionSerializer(serializers.Serializer):
    """Esquema descriptivo de los tipos de acción auditables."""

    action = serializers.IntegerField()
    name = serializers.CharField()
    label = serializers.CharField()
