from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.account"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import AccessPreset, User

        for model, options in (
            (User, {"exclude_fields": ["password", "session_key"]}),
            (AccessPreset, {}),
        ):
            if not auditlog.contains(model):
                auditlog.register(model, **options)
