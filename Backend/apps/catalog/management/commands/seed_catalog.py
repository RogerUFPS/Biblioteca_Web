from django.core.management.base import BaseCommand

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    Country,
    Editorial,
    Institution,
    KnowledgeArea,
    Language,
    MaterialType,
)


class Command(BaseCommand):
    help = "Carga datos base del catálogo de forma idempotente."

    def handle(self, *_args, **_options):
        user = User.all_objects.get(code=0)
        records = (
            (Language, {"abbreviation": "es", "name": "español"}),
            (Language, {"abbreviation": "en", "name": "inglés"}),
            (Country, {"name": "colombia", "abbreviation": "CO", "emoji_flag": "🇨🇴"}),
            (Country, {"name": "méxico", "abbreviation": "MX", "emoji_flag": "🇲🇽"}),
            (MaterialType, {"name": "artículo"}),
            (MaterialType, {"name": "libro"}),
            (Institution, {"name": "universidad francisco de paula santander"}),
            (Editorial, {"name": "editorial académica"}),
            (KnowledgeArea, {"name": "ciencias de la computación"}),
            (KnowledgeArea, {"name": "ingeniería"}),
            (AcademicProgram, {"name": "ingeniería de sistemas"}),
        )

        created_count = 0
        for model, values in records:
            instance, created = model.all_objects.get_or_create(
                **values,
                defaults={"created_by": user},
            )
            if created:
                created_count += 1
            elif instance.deleted_at is not None:
                instance.restore()

        self.stdout.write(
            self.style.SUCCESS(f"Catálogo cargado. Registros creados: {created_count}.")
        )
