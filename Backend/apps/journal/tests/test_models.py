from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    Country,
    KnowledgeArea,
    Language,
    MaterialType,
)
from apps.journal.models import (
    Journal,
    SharedJournalAcademicProgram,
    SharedJournalCountry,
    SharedJournalKnowledgeArea,
    SharedJournalLanguage,
    SharedJournalMaterialType,
    SharedJournalPlatform,
)
from apps.platforms.models import Platform


class JournalModelsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.system = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
        )

        cls.language = Language.objects.create(
            name="Español",
            abbreviation="es",
            created_by=cls.system,
        )

        cls.country = Country.objects.create(
            name="Colombia",
            abbreviation="co",
            emoji_flag="🇨🇴",
            created_by=cls.system,
        )

        cls.knowledge_area = KnowledgeArea.objects.create(
            name="Ingeniería",
            created_by=cls.system,
        )

        cls.material_type = MaterialType.objects.create(
            name="Artículos",
            created_by=cls.system,
        )

        cls.academic_program = AcademicProgram.objects.create(
            name="Ingeniería de Sistemas",
            created_by=cls.system,
        )

        cls.platform = Platform.objects.create(
            name="Scopus Test",
            is_harvestable=True,
            base_api_url="https://api.test.org",
            created_by=cls.system,
        )

    # ==========================================================================
    # JOURNAL
    # ==========================================================================

    def test_journal_creation(self):
        """Una revista debe poder crearse con su ISSN y título."""
        journal = Journal.objects.create(
            issn="1234-5678",
            title="Revista de Ingeniería",
            created_by=self.system,
        )

        self.assertIsNotNone(journal.pk)
        self.assertEqual(journal.issn, "1234-5678")
        self.assertEqual(journal.title, "Revista de Ingeniería")
        self.assertFalse(journal.active)
        self.assertIsNone(journal.validated_by)
        self.assertIsNone(journal.validated_at)

    def test_journal_issn_case_insensitive_unique_constraint(self):
        """El ISSN debe ser único sin importar mayúsculas/minúsculas."""
        Journal.objects.create(
            issn="1234-567X",
            title="Revista Uno",
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Journal.objects.create(
                    issn="1234-567x",
                    title="Revista Dos",
                    created_by=self.system,
                )

    def test_journal_soft_delete_and_restore(self):
        """Verifica el ciclo de vida de Soft Delete en Journal."""
        journal = Journal.objects.create(
            issn="1111-2222",
            title="Journal de Prueba",
            created_by=self.system,
        )

        pk = journal.pk

        journal.soft_delete(
            user=self.system,
            explanation="Prueba de eliminación lógica",
        )

        self.assertTrue(journal.is_deleted)
        self.assertFalse(
            Journal.objects.filter(pk=pk).exists()
        )
        self.assertTrue(
            Journal.all_objects.filter(pk=pk).exists()
        )

        journal.restore()

        self.assertFalse(journal.is_deleted)
        self.assertTrue(
            Journal.objects.filter(pk=pk).exists()
        )

    def test_journal_str_representation(self):
        """__str__ debe incluir el título y el ISSN."""
        journal = Journal.objects.create(
            issn="2222-3333",
            title="Plos One",
            created_by=self.system,
        )

        self.assertEqual(
            str(journal),
            "Plos One (2222-3333)",
        )

    # ==========================================================================
    # RELACIONES JOURNAL - LANGUAGE
    # ==========================================================================

    def test_shared_journal_language_unique_constraint(self):
        """No se debe poder duplicar la relación Journal - Language."""
        journal = Journal.objects.create(
            issn="3333-4444",
            title="Journal Languages",
            created_by=self.system,
        )

        SharedJournalLanguage.objects.create(
            journal=journal,
            language=self.language,
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedJournalLanguage.objects.create(
                    journal=journal,
                    language=self.language,
                    created_by=self.system,
                )

    # ==========================================================================
    # RELACIONES JOURNAL - COUNTRY
    # ==========================================================================

    def test_shared_journal_country_unique_constraint(self):
        """No se debe poder duplicar la relación Journal - Country."""
        journal = Journal.objects.create(
            issn="4444-5555",
            title="Journal Countries",
            created_by=self.system,
        )

        SharedJournalCountry.objects.create(
            journal=journal,
            country=self.country,
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedJournalCountry.objects.create(
                    journal=journal,
                    country=self.country,
                    created_by=self.system,
                )

    # ==========================================================================
    # RELACIONES JOURNAL - KNOWLEDGE AREA
    # ==========================================================================

    def test_shared_journal_knowledge_area_unique_constraint(self):
        """No se debe poder duplicar la relación Journal - KnowledgeArea."""
        journal = Journal.objects.create(
            issn="5555-6666",
            title="Journal Knowledge Areas",
            created_by=self.system,
        )

        SharedJournalKnowledgeArea.objects.create(
            journal=journal,
            knowledge_area=self.knowledge_area,
            is_manual=True,
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedJournalKnowledgeArea.objects.create(
                    journal=journal,
                    knowledge_area=self.knowledge_area,
                    is_manual=True,
                    created_by=self.system,
                )

    def test_active_knowledge_area_relation_requires_an_origin(self):
        journal = Journal.objects.create(
            issn="5656-7878",
            title="Journal Area Origin",
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedJournalKnowledgeArea.objects.create(
                    journal=journal,
                    knowledge_area=self.knowledge_area,
                    is_manual=False,
                    is_derived=False,
                    created_by=self.system,
                )

    # ==========================================================================
    # RELACIONES JOURNAL - MATERIAL TYPE
    # ==========================================================================

    def test_shared_journal_material_type_unique_constraint(self):
        """No se debe poder duplicar la relación Journal - MaterialType."""
        journal = Journal.objects.create(
            issn="6666-7777",
            title="Journal Material Types",
            created_by=self.system,
        )

        SharedJournalMaterialType.objects.create(
            journal=journal,
            material_type=self.material_type,
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedJournalMaterialType.objects.create(
                    journal=journal,
                    material_type=self.material_type,
                    created_by=self.system,
                )

    # ==========================================================================
    # RELACIONES JOURNAL - ACADEMIC PROGRAM
    # ==========================================================================

    def test_shared_journal_academic_program_unique_constraint(self):
        """No se debe poder duplicar la relación Journal - AcademicProgram."""
        journal = Journal.objects.create(
            issn="7777-8888",
            title="Journal Academic Programs",
            created_by=self.system,
        )

        SharedJournalAcademicProgram.objects.create(
            journal=journal,
            academic_program=self.academic_program,
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedJournalAcademicProgram.objects.create(
                    journal=journal,
                    academic_program=self.academic_program,
                    created_by=self.system,
                )

    # ==========================================================================
    # RELACIÓN JOURNAL - PLATFORM
    # ==========================================================================

    def test_shared_journal_platform_unique_constraint(self):
        """No se debe poder duplicar la relación Journal - Platform."""
        journal = Journal.objects.create(
            issn="8888-9999",
            title="Journal Platforms",
            created_by=self.system,
        )

        SharedJournalPlatform.objects.create(
            journal=journal,
            platform=self.platform,
            created_by=self.system,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SharedJournalPlatform.objects.create(
                    journal=journal,
                    platform=self.platform,
                    created_by=self.system,
                )

    def test_shared_journal_platform_fields(self):
        """
        SharedJournalPlatform debe almacenar correctamente
        los atributos propios de la relación.
        """
        journal = Journal.objects.create(
            issn="9999-1111",
            title="Journal Platform Fields",
            created_by=self.system,
        )

        link = SharedJournalPlatform.objects.create(
            journal=journal,
            platform=self.platform,
            has_full_text=True,
            created_by=self.system,
        )

        self.assertEqual(
            link.start_period,
            timezone.localdate(),
        )
        self.assertEqual(
            link.finish_period,
            None,
        )
        self.assertTrue(link.has_full_text)

        original_start = link.start_period
        link.soft_delete(self.system, "Fin de la vinculación")
        self.assertEqual(link.start_period, original_start)
        self.assertEqual(link.finish_period, timezone.localdate())

        link.restore()
        self.assertEqual(link.start_period, original_start)
        self.assertIsNone(link.finish_period)
