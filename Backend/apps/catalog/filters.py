import django_filters

from . import models


class SharedAcademicProgramKnowledgeAreaFilter(django_filters.FilterSet):
    class Meta:
        model = models.SharedAcademicProgramKnowledgeArea
        fields = ["knowledge_area", "academic_program"]
