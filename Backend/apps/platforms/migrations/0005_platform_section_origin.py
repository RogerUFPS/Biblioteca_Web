from django.db import migrations, models


SECTION_MODELS = (
    "sharedplatformsupport",
    "sharedplatformlanguage",
    "sharedplatformcountry",
    "sharedplatformknowledgearea",
    "sharedplatformmaterialtype",
    "sharedplatformacademicprogram",
)


def classify_existing_relations(apps, schema_editor):
    manual_models = (
        "SharedPlatformSupport",
        "SharedPlatformLanguage",
        "SharedPlatformCountry",
        "SharedPlatformMaterialType",
    )
    derived_models = (
        "SharedPlatformKnowledgeArea",
        "SharedPlatformAcademicProgram",
    )
    for model_name in manual_models:
        apps.get_model("platforms", model_name).objects.filter(
            deleted_at__isnull=True,
        ).update(is_manual=True, is_derived=False)
    for model_name in derived_models:
        apps.get_model("platforms", model_name).objects.filter(
            deleted_at__isnull=True,
        ).update(is_manual=False, is_derived=True)


class Migration(migrations.Migration):
    dependencies = [("platforms", "0004_platform_is_harvestable")]

    operations = [
        *[
            migrations.AddField(
                model_name=model_name,
                name="is_manual",
                field=models.BooleanField(default=False),
            )
            for model_name in SECTION_MODELS
        ],
        *[
            migrations.AddField(
                model_name=model_name,
                name="is_derived",
                field=models.BooleanField(default=False),
            )
            for model_name in SECTION_MODELS
        ],
        migrations.RunPython(
            classify_existing_relations,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
