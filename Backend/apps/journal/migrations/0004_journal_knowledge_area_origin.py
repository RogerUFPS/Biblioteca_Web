from django.db import migrations, models


def classify_historical_links(apps, schema_editor):
    SharedJournalKnowledgeArea = apps.get_model(
        "journal", "SharedJournalKnowledgeArea"
    )
    SharedJournalKnowledgeArea.objects.filter(deleted_at__isnull=True).update(
        is_manual=False,
        is_derived=True,
    )
    SharedJournalKnowledgeArea.objects.filter(deleted_at__isnull=False).update(
        is_manual=False,
        is_derived=False,
    )


class Migration(migrations.Migration):
    dependencies = [("journal", "0003_journal_publication_date_licenses")]

    operations = [
        migrations.AddField(
            model_name="sharedjournalknowledgearea",
            name="is_manual",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Indica si el área fue seleccionada manualmente en la revista."
                ),
            ),
        ),
        migrations.AddField(
            model_name="sharedjournalknowledgearea",
            name="is_derived",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Indica si el área proviene de programas académicos vigentes."
                ),
            ),
        ),
        migrations.RunPython(
            classify_historical_links,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="sharedjournalknowledgearea",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(deleted_at__isnull=False)
                    | models.Q(is_manual=True)
                    | models.Q(is_derived=True)
                ),
                name="journal_area_active_has_origin",
            ),
        ),
    ]
