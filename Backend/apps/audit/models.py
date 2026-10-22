from django.core.exceptions import PermissionDenied
from django.db import models
from auditlog.models import LogEntry


class AuditLog(LogEntry):
    """
    Modelo proxy inmutable para visualizar registros de auditoría del sistema.
    Garantiza que ningún registro de auditoría pueda ser alterado ni eliminado,
    cumpliendo con el requerimiento de integridad e inmutabilidad.
    """

    class Meta:
        proxy = True
        verbose_name = "Registro de auditoría"
        verbose_name_plural = "Registros de auditoría"
        ordering = ["-timestamp"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionDenied("Los registros de auditoría son estrictamente inmutables.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Los registros de auditoría no pueden ser eliminados.")

    @property
    def action_name(self) -> str:
        actions = {
            LogEntry.Action.CREATE: "create",
            LogEntry.Action.UPDATE: "update",
            LogEntry.Action.DELETE: "delete",
            LogEntry.Action.ACCESS: "access",
        }
        return actions.get(self.action, "unknown")

    @property
    def action_display(self) -> str:
        actions = {
            LogEntry.Action.CREATE: "Creación",
            LogEntry.Action.UPDATE: "Actualización",
            LogEntry.Action.DELETE: "Eliminación",
            LogEntry.Action.ACCESS: "Acceso",
        }
        return actions.get(self.action, "Desconocido")

    @property
    def resource(self) -> str:
        return self.content_type.model if self.content_type else ""

    @property
    def resource_display(self) -> str:
        if self.content_type and self.content_type.model_class():
            return str(self.content_type.model_class()._meta.verbose_name)
        return self.resource

    @property
    def is_soft_delete(self) -> bool:
        if self.action == LogEntry.Action.UPDATE and isinstance(self.changes, dict):
            deleted_at = self.changes.get("deleted_at")
            if deleted_at and isinstance(deleted_at, list) and len(deleted_at) == 2:
                return deleted_at[0] is None and deleted_at[1] is not None
        return False

    @property
    def is_restore(self) -> bool:
        if self.action == LogEntry.Action.UPDATE and isinstance(self.changes, dict):
            deleted_at = self.changes.get("deleted_at")
            if deleted_at and isinstance(deleted_at, list) and len(deleted_at) == 2:
                return deleted_at[0] is not None and deleted_at[1] is None
        return False
