from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("harvesting", "0006_harvest_api_marker_harvest_api_page_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="harvest",
            name="worker_checkpoint",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Versión del progreso procesada por los workers; evita pasos duplicados.",
            ),
        ),
        migrations.AddField(
            model_name="harvest",
            name="worker_elapsed_milliseconds",
            field=models.PositiveBigIntegerField(
                default=0,
                help_text="Tiempo activo acumulado procesando pasos del worker.",
            ),
        ),
        migrations.AddField(
            model_name="harvest",
            name="worker_dispatched_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Último despacho o paso confirmado por el worker de cosecha.",
                null=True,
            ),
        ),
    ]
