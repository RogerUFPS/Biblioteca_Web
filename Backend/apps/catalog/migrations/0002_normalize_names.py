from django.db import migrations


def normalize_names(apps, schema_editor):
    models = (
        apps.get_model("catalog", "Institution"),
        apps.get_model("catalog", "Language"),
        apps.get_model("catalog", "Country"),
        apps.get_model("catalog", "MaterialType"),
        apps.get_model("catalog", "Editorial"),
        apps.get_model("catalog", "KnowledgeArea"),
        apps.get_model("catalog", "AcademicProgram"),
    )
    for model in models:
        for instance in model.objects.all():
            normalized = instance.name.strip().lower()
            if instance.name != normalized:
                model.objects.filter(pk=instance.pk).update(name=normalized)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalize_names, migrations.RunPython.noop),
    ]
