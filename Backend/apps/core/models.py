from django.conf import settings
from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet con filtros para registros activos y eliminados."""

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)


class AliveManager(models.Manager):
    """Manager predeterminado que devuelve solo registros activos."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()


class SoftDeleteMixin(models.Model):
    """Campos y operaciones comunes para el borrado lógico."""

    delete_explanation = models.CharField(max_length=500, null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, user, explanation: str):
        if not explanation or not explanation.strip():
            raise ValueError("Se requiere una explicación para eliminar.")

        self.deleted_by = user
        self.deleted_at = timezone.now()
        self.delete_explanation = explanation.strip()
        self.save(update_fields=["deleted_by", "deleted_at", "delete_explanation"])

    def restore(self):
        self.deleted_by = None
        self.deleted_at = None
        self.delete_explanation = None
        self.save(update_fields=["deleted_by", "deleted_at", "delete_explanation"])


class AuditableModel(SoftDeleteMixin):
    """Modelo abstracto con auditoría y borrado lógico reutilizables."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_updated",
    )
    updated_at = models.DateTimeField(null=True, blank=True)

    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_deleted",
    )

    objects = AliveManager()
    all_objects = models.Manager()

    def save(self, *args, **kwargs):
        if hasattr(self, "name") and isinstance(self.name, str):
            self.name = self.name.strip().lower()
        return super().save(*args, **kwargs)

    class Meta:
        abstract = True
