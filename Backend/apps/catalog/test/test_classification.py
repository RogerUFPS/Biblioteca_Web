from django.test import TestCase

from apps.account.models import User
from apps.catalog import models, serializers


class AcademicProgramClassificationSerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0, full_name="Sistema", email="catalog-classification@test.local"
        )
        cls.area = models.KnowledgeArea.objects.create(
            name="ingenieria", created_by=cls.user
        )
        cls.program = models.AcademicProgram.objects.create(
            name="sistemas", created_by=cls.user
        )
        models.SharedAcademicProgramKnowledgeArea.objects.create(
            academic_program=cls.program,
            knowledge_area=cls.area,
            created_by=cls.user,
        )

    def test_empty_areas_requires_explicit_confirmation(self):
        serializer = serializers.AcademicProgramSerializer(
            self.program, data={"knowledge_areas": []}, partial=True
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("confirm_empty_knowledge_areas", serializer.errors)

    def test_confirmed_empty_areas_soft_deletes_relation(self):
        serializer = serializers.AcademicProgramSerializer(
            self.program,
            data={
                "knowledge_areas": [],
                "confirm_empty_knowledge_areas": True,
            },
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.user)
        link = models.SharedAcademicProgramKnowledgeArea.all_objects.get(
            academic_program=self.program, knowledge_area=self.area
        )
        self.assertIsNotNone(link.deleted_at)
        self.assertEqual(link.deleted_by, self.user)

    def test_patch_without_areas_keeps_relations(self):
        serializer = serializers.AcademicProgramSerializer(
            self.program, data={"name": "sistemas actualizado"}, partial=True
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save(updated_by=self.user)
        self.assertTrue(
            models.SharedAcademicProgramKnowledgeArea.objects.filter(
                academic_program=self.program, knowledge_area=self.area
            ).exists()
        )
