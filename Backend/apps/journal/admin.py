from django.contrib import admin

from . import models


for model in [
    models.Journal,
    models.SharedJournalLanguage,
    models.SharedJournalCountry,
    models.SharedJournalKnowledgeArea,
    models.SharedJournalMaterialType,
    models.SharedJournalAcademicProgram,
    models.SharedJournalPlatform,
]:
    admin.site.register(model)