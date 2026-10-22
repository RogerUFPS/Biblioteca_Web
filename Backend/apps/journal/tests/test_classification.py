from django.test import TestCase
from django.utils import timezone

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    KnowledgeArea,
    SharedAcademicProgramKnowledgeArea,
)
from apps.journal import models
from apps.journal.classification import (
    propagate_catalog_change,
    recalculate_journals,
    sync_manual_knowledge_areas,
)


class JournalClassificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0, full_name="Sistema", email="journal-classification@test.local"
        )
        cls.area_a = KnowledgeArea.objects.create(name="area a", created_by=cls.user)
        cls.area_b = KnowledgeArea.objects.create(name="area b", created_by=cls.user)
        cls.program_a = AcademicProgram.objects.create(name="programa a", created_by=cls.user)
        cls.program_b = AcademicProgram.objects.create(name="programa b", created_by=cls.user)
        for program, area in (
            (cls.program_a, cls.area_a),
            (cls.program_a, cls.area_b),
            (cls.program_b, cls.area_b),
        ):
            SharedAcademicProgramKnowledgeArea.objects.create(
                academic_program=program, knowledge_area=area, created_by=cls.user
            )

    def _journal(self, *, validated=False):
        return models.Journal.objects.create(
            issn="1234-5678", title="Journal",
            active=validated,
            validated_by=self.user if validated else None,
            validated_at=timezone.now() if validated else None,
            created_by=self.user,
        )

    def test_areas_are_full_union_without_duplicates(self):
        journal = self._journal()
        for program in (self.program_a, self.program_b):
            models.SharedJournalAcademicProgram.objects.create(
                journal=journal, academic_program=program, created_by=self.user
            )
        recalculate_journals([journal.pk], user=self.user)
        self.assertEqual(
            set(journal.knowledge_area_links.values_list("knowledge_area_id", flat=True)),
            {self.area_a.pk, self.area_b.pk},
        )
        area_b_link = journal.knowledge_area_links.get(knowledge_area=self.area_b)
        self.assertFalse(area_b_link.is_manual)
        self.assertTrue(area_b_link.is_derived)
        self.assertFalse(area_b_link.editable)

    def test_equal_effective_result_does_not_invalidate(self):
        journal = self._journal(validated=True)
        for program in (self.program_a, self.program_b):
            models.SharedJournalAcademicProgram.objects.create(
                journal=journal, academic_program=program, created_by=self.user
            )
        recalculate_journals([journal.pk], user=self.user, invalidate_on_change=False)
        link = SharedAcademicProgramKnowledgeArea.objects.get(
            academic_program=self.program_a, knowledge_area=self.area_b
        )
        link.soft_delete(user=self.user, explanation="Área todavía aportada por B")
        propagate_catalog_change([self.program_a.pk], user=self.user)
        journal.refresh_from_db()
        self.assertTrue(journal.active)
        self.assertIsNotNone(journal.validated_at)
        area_link = journal.knowledge_area_links.get(knowledge_area=self.area_b)
        self.assertTrue(area_link.is_derived)
        self.assertIsNone(area_link.deleted_at)

    def test_derived_link_is_soft_deleted_and_restored(self):
        journal = self._journal()
        source = models.SharedJournalAcademicProgram.objects.create(
            journal=journal, academic_program=self.program_a, created_by=self.user
        )
        recalculate_journals([journal.pk], user=self.user)
        derived = models.SharedJournalKnowledgeArea.objects.get(
            journal=journal, knowledge_area=self.area_a
        )
        source.soft_delete(user=self.user, explanation="Cambio de programa")
        recalculate_journals([journal.pk], user=self.user)
        derived.refresh_from_db()
        self.assertIsNotNone(derived.deleted_at)
        self.assertEqual(derived.deleted_by, self.user)
        self.assertFalse(derived.is_manual)
        self.assertFalse(derived.is_derived)
        source.restore()
        recalculate_journals([journal.pk], user=self.user)
        derived.refresh_from_db()
        self.assertIsNone(derived.deleted_at)
        self.assertFalse(derived.is_manual)
        self.assertTrue(derived.is_derived)

    def test_manual_area_becomes_derived_and_returns_to_editable(self):
        journal = self._journal()
        sync_manual_knowledge_areas(journal, [self.area_a], user=self.user)
        area_link = journal.knowledge_area_links.get(knowledge_area=self.area_a)
        self.assertTrue(area_link.is_manual)
        self.assertFalse(area_link.is_derived)
        self.assertTrue(area_link.editable)

        program_link = models.SharedJournalAcademicProgram.objects.create(
            journal=journal,
            academic_program=self.program_a,
            created_by=self.user,
        )
        recalculate_journals([journal.pk], user=self.user)
        area_link.refresh_from_db()
        self.assertTrue(area_link.is_manual)
        self.assertTrue(area_link.is_derived)
        self.assertFalse(area_link.editable)

        # La selección manual no puede retirarse mientras el área sea derivada.
        sync_manual_knowledge_areas(journal, [], user=self.user)
        area_link.refresh_from_db()
        self.assertTrue(area_link.is_manual)
        self.assertTrue(area_link.is_derived)

        program_link.soft_delete(user=self.user, explanation="Retirar programa")
        recalculate_journals([journal.pk], user=self.user)
        area_link.refresh_from_db()
        self.assertTrue(area_link.is_manual)
        self.assertFalse(area_link.is_derived)
        self.assertTrue(area_link.editable)

    def test_manual_removal_soft_deletes_and_resets_origins(self):
        journal = self._journal()
        sync_manual_knowledge_areas(journal, [self.area_a], user=self.user)
        link = journal.knowledge_area_links.get(knowledge_area=self.area_a)

        sync_manual_knowledge_areas(journal, [], user=self.user)

        link.refresh_from_db()
        self.assertIsNotNone(link.deleted_at)
        self.assertFalse(link.is_manual)
        self.assertFalse(link.is_derived)
