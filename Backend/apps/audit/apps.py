from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
    verbose_name = "Auditoría"

    def ready(self):
        from .registry import register_auditlog_models

        register_auditlog_models()
