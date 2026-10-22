from django.db import migrations, models


def normalize_unverified_links(apps, schema_editor):
    LinkCheckLog = apps.get_model("platforms", "LinkCheckLog")
    LinkCheckLog.objects.filter(last_check__isnull=True).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("platforms", "0005_platform_section_origin")]

    operations = [
        migrations.AlterField(
            model_name="linkchecklog",
            name="is_active",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Indica si el enlace respondió correctamente. Solo representa "
                    "disponibilidad cuando last_check no es nulo."
                ),
            ),
        ),
        migrations.AlterModelOptions(
            name="linkchecklog",
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.RunPython(
            normalize_unverified_links,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="linkchecklog",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(last_check__isnull=False)
                    | models.Q(is_active=False)
                ),
                name="link_log_active_requires_check",
            ),
        ),
    ]
