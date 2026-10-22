import hashlib

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import SoftDeleteMixin, SoftDeleteQuerySet


class UserManager(BaseUserManager):
    """Manager por defecto: excluye cuentas eliminadas lógicamente."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def create_user(
        self,
        email=None,
        password=None,
        *,
        code=None,
        created_by=None,
        **extra_fields,
    ):
        if not email:
            raise ValueError("El correo electrónico es obligatorio.")
        email = self.normalize_email(email).strip().lower()
        user = self.model(
            email=email,
            code=code,
            created_by=created_by,
            **extra_fields,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        if not password:
            raise ValueError("El superadmin debe tener una contraseña.")
        extra_fields.setdefault("is_superadmin", True)
        return self.create_user(email, password, **extra_fields)


class User(SoftDeleteMixin, AbstractBaseUser):
    """Cuenta autenticada por correo electrónico."""

    code = models.IntegerField(unique=True, null=True, blank=True)
    collegue_code = models.CharField(max_length=64, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_superadmin = models.BooleanField(default=False)
    force_password_change = models.BooleanField(default=False)
    permissions = models.JSONField(default=dict, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True)

    created_by = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users_updated",
    )
    updated_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users_deleted",
    )
    presets = models.ManyToManyField(
        "AccessPreset",
        blank=True,
        related_name="users",
    )

    objects = UserManager()
    all_objects = models.Manager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.full_name or self.email

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        return super().save(*args, **kwargs)

    def effective_permissions(self):
        if self.is_superadmin:
            from .permissions import PERMISSION_MATRIX

            return PERMISSION_MATRIX
        result = {}
        permission_sets = [self.permissions or {}]
        permission_sets.extend(
            preset.permissions for preset in self.presets.all()
        )
        for permission_set in permission_sets:
            for app, resources in permission_set.items():
                app_permissions = result.setdefault(app, {})
                for resource, actions in resources.items():
                    resource_permissions = app_permissions.setdefault(resource, {})
                    for action, enabled in actions.items():
                        resource_permissions[action] = (
                            resource_permissions.get(action, False) or bool(enabled)
                        )
        return result


class AccessPreset(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=500, blank=True)
    permissions = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="access_presets_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="access_presets_updated",
    )
    updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SessionTermination(models.Model):
    class Reason(models.TextChoices):
        LOGIN_REPLACED = "login_replaced", "Sesión reemplazada"
        CREDENTIALS_RESET = "credentials_reset", "Credenciales restablecidas"
        ACCOUNT_DISABLED = "account_disabled", "Cuenta desactivada"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session_key_hash = models.CharField(max_length=64, unique=True)
    reason = models.CharField(
        max_length=32,
        choices=Reason.choices,
        default=Reason.LOGIN_REPLACED,
    )
    created_at = models.DateTimeField(default=timezone.now)

    @classmethod
    def record(cls, user, session_key, reason=Reason.LOGIN_REPLACED):
        if session_key:
            cls.objects.update_or_create(
                session_key_hash=hashlib.sha256(
                    session_key.encode("utf-8")
                ).hexdigest(),
                defaults={"user": user, "reason": reason},
            )
