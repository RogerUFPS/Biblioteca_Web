from django.test import TestCase
from django.utils import timezone

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    KnowledgeArea,
    SharedAcademicProgramKnowledgeArea,
)
from apps.journal import models as journal_models
from apps.platforms import models
from apps.platforms.classification import recalculate_platforms


class PlatformClassificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0, full_name="Sistema", email="platform-classification@test.local"
        )
        cls.area = KnowledgeArea.objects.create(name="area platform", created_by=cls.user)
        cls.program = AcademicProgram.objects.create(name="programa platform", created_by=cls.user)
        SharedAcademicProgramKnowledgeArea.objects.create(
            academic_program=cls.program, knowledge_area=cls.area, created_by=cls.user
        )

    def _journal(self, issn, *, eligible):
        return journal_models.Journal.objects.create(
            issn=issn, title=issn, active=eligible,
            validated_by=self.user if eligible else None,
            validated_at=timezone.now() if eligible else None,
            created_by=self.user,
        )

    def test_uses_only_eligible_journals(self):
        platform = models.Platform.objects.create(name="platform", created_by=self.user)
        eligible = self._journal("1111-1111", eligible=True)
        inactive = self._journal("2222-2222", eligible=False)
        for journal in (eligible, inactive):
            journal_models.SharedJournalAcademicProgram.objects.create(
                journal=journal, academic_program=self.program, created_by=self.user
            )
            journal_models.SharedJournalKnowledgeArea.objects.create(
                journal=journal, knowledge_area=self.area,
                is_derived=True, created_by=self.user
            )
            journal_models.SharedJournalPlatform.objects.create(
                journal=journal, platform=platform, created_by=self.user
            )
        recalculate_platforms([platform.pk], user=self.user)
        self.assertEqual(
            set(models.SharedPlatformAcademicProgram.objects.filter(platform=platform)
                .values_list("academic_program_id", flat=True)),
            {self.program.pk},
        )
        self.assertEqual(
            set(models.SharedPlatformKnowledgeArea.objects.filter(platform=platform)
                .values_list("knowledge_area_id", flat=True)),
            {self.area.pk},
        )
        link = models.SharedPlatformAcademicProgram.objects.get(
            platform=platform, academic_program=self.program,
        )
        self.assertFalse(link.is_manual)
        self.assertTrue(link.is_derived)

    def test_incomplete_eligible_classification_moves_published_to_draft(self):
        platform = models.Platform.objects.create(
            name="incomplete", status=models.Platform.Status.PUBLICADO,
            validated_by=self.user, validated_at=timezone.now(), created_by=self.user,
        )
        journal = self._journal("3333-3333", eligible=True)
        journal_models.SharedJournalPlatform.objects.create(
            journal=journal, platform=platform, created_by=self.user
        )
        recalculate_platforms([platform.pk], user=self.user)
        platform.refresh_from_db()
        self.assertEqual(platform.status, models.Platform.Status.BORRADOR)
        self.assertIsNone(platform.validated_by)
        self.assertIsNone(platform.validated_at)

    def test_effective_manual_journal_area_is_derived_in_platform(self):
        platform = models.Platform.objects.create(
            name="platform manual journal area", created_by=self.user
        )
        journal = self._journal("4444-4444", eligible=True)
        manual_area = KnowledgeArea.objects.create(
            name="area manual journal", created_by=self.user
        )
        journal_models.SharedJournalKnowledgeArea.objects.create(
            journal=journal,
            knowledge_area=manual_area,
            is_manual=True,
            is_derived=False,
            created_by=self.user,
        )
        journal_models.SharedJournalPlatform.objects.create(
            journal=journal, platform=platform, created_by=self.user
        )

        recalculate_platforms([platform.pk], user=self.user)

        link = models.SharedPlatformKnowledgeArea.objects.get(
            platform=platform, knowledge_area=manual_area
        )
        self.assertFalse(link.is_manual)
        self.assertTrue(link.is_derived)
