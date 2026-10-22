from django.contrib import admin

from . import models


@admin.register(models.Platform)
class PlatformAdmin(admin.ModelAdmin):
    exclude = ("encrypted_api_key",)


for model in [
    models.ValidSintaxis,
    models.LinkCheckLog,
    models.SharedPlatformSupport,
    models.SharedPlatformLanguage,
    models.SharedPlatformCountry,
    models.SharedPlatformKnowledgeArea,
    models.SharedPlatformMaterialType,
    models.SharedPlatformAcademicProgram,
]:
    admin.site.register(model)
