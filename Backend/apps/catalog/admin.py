from django.contrib import admin

from . import models


for model in [
    models.Institution,
    models.Language,
    models.Country,
    models.MaterialType,
    models.Editorial,
    models.KnowledgeArea,
    models.AcademicProgram,
    models.SharedAcademicProgramKnowledgeArea,
]:
    admin.site.register(model)
