from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("harvesting", "0004_harvest_elapsed_seconds"),
        ("journal", "0003_journal_publication_date_licenses"),
    ]

    operations = [
        migrations.CreateModel(
            name="HarvestJournal",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "result",
                    models.CharField(
                        choices=[("added", "Added"), ("updated", "Updated")],
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "harvest",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="journal_records",
                        to="harvesting.harvest",
                    ),
                ),
                (
                    "journal",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="harvest_records",
                        to="journal.journal",
                    ),
                ),
            ],
            options={
                "ordering": ["journal__title", "journal_id"],
            },
        ),
    ]
