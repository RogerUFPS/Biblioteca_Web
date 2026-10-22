from django.test import TestCase

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    KnowledgeArea,
    SharedAcademicProgramKnowledgeArea,
)
from apps.core.relations import sync_auditable_relation_ids


class AuditableRelationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0, full_name="Sistema", email="core-relations@test.local"
        )
        cls.program = AcademicProgram.objects.create(
            name="programa core", created_by=cls.user
        )
        cls.area = KnowledgeArea.objects.create(name="area core", created_by=cls.user)

    def _sync(self, desired_ids):
        return sync_auditable_relation_ids(
            through_model=SharedAcademicProgramKnowledgeArea,
            parent_field="academic_program",
            parent_id=self.program.pk,
            related_field="knowledge_area",
            desired_ids=desired_ids,
            user=self.user,
            delete_explanation="Sincronización de prueba.",
        )

    def test_create_soft_delete_restore_and_idempotency(self):
        self.assertTrue(self._sync([self.area.pk]))
        link = SharedAcademicProgramKnowledgeArea.objects.get(
            academic_program=self.program, knowledge_area=self.area
        )
        self.assertEqual(link.created_by, self.user)

        self.assertFalse(self._sync([self.area.pk]))

        self.assertTrue(self._sync([]))
        link.refresh_from_db()
        self.assertIsNotNone(link.deleted_at)
        self.assertEqual(link.deleted_by, self.user)
        self.assertEqual(link.delete_explanation, "Sincronización de prueba.")

        self.assertTrue(self._sync([self.area.pk]))
        restored = SharedAcademicProgramKnowledgeArea.objects.get(
            academic_program=self.program, knowledge_area=self.area
        )
        self.assertEqual(restored.pk, link.pk)
        self.assertIsNone(restored.deleted_at)
        self.assertIsNone(restored.deleted_by)
        self.assertIsNone(restored.delete_explanation)
