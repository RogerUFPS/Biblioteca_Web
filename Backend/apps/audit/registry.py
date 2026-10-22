"""
Registro centralizado de modelos a auditar mediante django-auditlog.
"""
import logging
from auditlog.registry import auditlog

logger = logging.getLogger(__name__)


def register_auditlog_models():
    """
    Registra todos los modelos de la base de datos utilizados en la aplicación web
    para vigilar de forma continua e inmutable las operaciones de creación,
    actualización y eliminación.
    """
    from apps.account.models import User
    from apps.catalog.models import (
        AcademicProgram,
        Country,
        Editorial,
        Institution,
        KnowledgeArea,
        Language,
        MaterialType,
        SharedAcademicProgramKnowledgeArea,
    )
    from apps.harvesting.models import (
        Harvest,
        Schedule,
        ScheduleEvent,
    )
    from apps.journal.models import (
        Journal,
        SharedJournalAcademicProgram,
        SharedJournalCountry,
        SharedJournalKnowledgeArea,
        SharedJournalLanguage,
        SharedJournalMaterialType,
        SharedJournalPlatform,
    )
    from apps.platforms.models import (
        LinkCheckLog,
        Platform,
        SharedPlatformAcademicProgram,
        SharedPlatformCountry,
        SharedPlatformKnowledgeArea,
        SharedPlatformLanguage,
        SharedPlatformMaterialType,
        SharedPlatformSupport,
        ValidSintaxis,
    )

    models_config = [
        # Catálogo
        (Institution, {}),
        (Language, {}),
        (Country, {}),
        (MaterialType, {}),
        (Editorial, {}),
        (KnowledgeArea, {}),
        (AcademicProgram, {}),
        (SharedAcademicProgramKnowledgeArea, {}),

        # Plataformas (se excluye la clave secreta encriptada por seguridad)
        (Platform, {"exclude_fields": ["encrypted_api_key"]}),
        (ValidSintaxis, {}),
        (LinkCheckLog, {}),
        (SharedPlatformSupport, {}),
        (SharedPlatformLanguage, {}),
        (SharedPlatformCountry, {}),
        (SharedPlatformKnowledgeArea, {}),
        (SharedPlatformMaterialType, {}),
        (SharedPlatformAcademicProgram, {}),

        # Revistas
        (Journal, {}),
        (SharedJournalLanguage, {}),
        (SharedJournalCountry, {}),
        (SharedJournalKnowledgeArea, {}),
        (SharedJournalMaterialType, {}),
        (SharedJournalAcademicProgram, {}),
        (SharedJournalPlatform, {}),

        # Cosechas
        (Schedule, {"m2m_fields": {"platforms"}}),
        (ScheduleEvent, {}),
        (Harvest, {}),

        # Usuarios (se excluye la contraseña y session_key por seguridad)
        (User, {"exclude_fields": ["password", "session_key"]}),
    ]

    for model, kwargs in models_config:
        try:
            if not auditlog.contains(model):
                auditlog.register(model, **kwargs)
        except Exception as exc:
            logger.warning("No se pudo registrar %s en auditlog: %s", model.__name__, exc)
