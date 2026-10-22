from django.core.management.base import BaseCommand
from apps.harvesting.services import run_scheduled_harvests


class Command(BaseCommand):
    help = "Encola los eventos vencidos de las programaciones activas de cosecha."

    def handle(self, *args, **options):
        self.stdout.write("Evaluando programaciones de cosecha...")
        harvests = run_scheduled_harvests()
        if not harvests:
            self.stdout.write(
                self.style.SUCCESS(
                    "No hay cosechas pendientes de despacho en este momento."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Se encolaron {len(harvests)} Harvest: {[h.pk for h in harvests]}."
                )
            )
