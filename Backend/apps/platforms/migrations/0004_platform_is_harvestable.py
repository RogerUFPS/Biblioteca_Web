from django.db import migrations, models


def infer_harvestability_from_base_api_url(apps, schema_editor):
    Platform = apps.get_model("platforms", "Platform")
    Platform._base_manager.filter(
        base_api_url__isnull=False,
    ).exclude(
        base_api_url="",
    ).update(
        is_harvestable=True,
    )


def reset_harvestability(apps, schema_editor):
    Platform = apps.get_model("platforms", "Platform")
    Platform._base_manager.update(is_harvestable=False)


class Migration(migrations.Migration):

    dependencies = [
        ("platforms", "0003_alter_linkchecklog_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="platform",
            name="is_harvestable",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Indica si el sistema dispone de un mecanismo de cosecha "
                    "para esta plataforma."
                ),
            ),
        ),
        migrations.RunPython(
            infer_harvestability_from_base_api_url,
            reset_harvestability,
        ),
    ]
