import django.db.models.deletion
import django.db.models.functions.text
from django.conf import settings
from django.db import migrations, models


def migrate_legacy_licenses(apps, schema_editor):
    Journal = apps.get_model("journal", "Journal")
    License = apps.get_model("journal", "License")
    SharedJournalLicense = apps.get_model("journal", "SharedJournalLicense")

    for journal in Journal.objects.exclude(license__isnull=True).exclude(license=""):
        name = journal.license.strip()
        if not name:
            continue
        license_obj = License.objects.filter(name__iexact=name).first()
        if license_obj is None:
            license_obj = License.objects.create(name=name, created_by_id=journal.created_by_id)
        SharedJournalLicense.objects.get_or_create(
            journal_id=journal.pk,
            license_id=license_obj.pk,
            defaults={"created_by_id": journal.created_by_id},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("journal", "0002_alter_journal_active"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="journal",
            name="publication_date",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Fecha propia de publicación u origen de la revista.",
            ),
        ),
        migrations.CreateModel(
            name="License",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("delete_explanation", models.CharField(blank=True, max_length=500, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("name", models.CharField(max_length=255)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_updated", to=settings.AUTH_USER_MODEL)),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_deleted", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddConstraint(
            model_name="license",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                name="unique_journal_license_name_ci",
            ),
        ),
        migrations.CreateModel(
            name="SharedJournalLicense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("delete_explanation", models.CharField(blank=True, max_length=500, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_updated", to=settings.AUTH_USER_MODEL)),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="%(app_label)s_%(class)s_deleted", to=settings.AUTH_USER_MODEL)),
                ("journal", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="license_links", to="journal.journal")),
                ("license", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="journal_links", to="journal.license")),
            ],
            options={"ordering": ["journal_id", "license_id"]},
        ),
        migrations.AddConstraint(
            model_name="sharedjournallicense",
            constraint=models.UniqueConstraint(
                fields=("journal", "license"),
                name="unique_journal_license",
            ),
        ),
        migrations.RunPython(migrate_legacy_licenses, migrations.RunPython.noop),
        migrations.RemoveField(model_name="journal", name="license"),
        migrations.RemoveField(model_name="journal", name="start_period"),
        migrations.RemoveField(model_name="journal", name="finish_period"),
    ]
