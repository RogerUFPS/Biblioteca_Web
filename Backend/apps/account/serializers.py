from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import AccessPreset, User
from .permissions import normalize_permissions


class UserSerializer(serializers.ModelSerializer):
    effective_permissions = serializers.SerializerMethodField()
    presets = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "collegue_code",
            "full_name",
            "is_active",
            "is_superadmin",
            "force_password_change",
            "permissions",
            "effective_permissions",
            "presets",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "is_active",
            "is_superadmin",
            "force_password_change",
            "effective_permissions",
            "presets",
            "created_at",
            "updated_at",
        )

    def get_effective_permissions(self, user):
        return user.effective_permissions()

    def validate_permissions(self, value):
        try:
            return normalize_permissions(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("email", "full_name", "collegue_code")

    def validate_email(self, value):
        value = value.strip().lower()
        if User.all_objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("Ya existe una cuenta con este correo.")
        return value


class UserAdminUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("full_name", "collegue_code", "is_active")


class AccessPresetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccessPreset
        fields = ("id", "name", "description", "permissions", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_name(self, value):
        return value.strip()

    def validate_permissions(self, value):
        try:
            return normalize_permissions(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error


class RegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    collegue_code = serializers.CharField(required=False, allow_blank=True, max_length=64)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.all_objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Ya existe una cuenta con este correo.")
        return value

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_new_password(self, value):
        try:
            validate_password(value, self.context["request"].user)
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    collegue_code = serializers.CharField(required=False, allow_blank=True, max_length=64)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.all_objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Ya existe una cuenta con este correo.")
        return value


class AssignPresetsSerializer(serializers.Serializer):
    preset_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
    )

    def validate_preset_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("No se permiten presets duplicados.")
        if AccessPreset.objects.filter(pk__in=value).count() != len(value):
            raise serializers.ValidationError("Uno o más presets no existen.")
        return value


class UserPermissionsSerializer(serializers.Serializer):
    permissions = serializers.JSONField()

    def validate_permissions(self, value):
        try:
            return normalize_permissions(value)
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error
