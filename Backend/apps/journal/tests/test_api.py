from typing import Any

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    Country,
    Editorial,
    Institution,
    KnowledgeArea,
    Language,
    MaterialType,
    SharedAcademicProgramKnowledgeArea,
)
from apps.journal import models
from apps.platforms import models as platform_models
from apps.platforms.models import Platform


class JournalAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.system = User.objects.create_user(
            code=0,
            full_name="Sistema",
            email="sistema@test.local",
            is_superadmin=True,
        )

        cls.editorial = Editorial.objects.create(
            name="Nature Publishing",
            created_by=cls.system,
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
            name="Ciencias Naturales",
            created_by=cls.system,
        )

        cls.material_type = MaterialType.objects.create(
            name="Artículos",
            created_by=cls.system,
        )

        cls.academic_program = AcademicProgram.objects.create(
            name="Biología",
            created_by=cls.system,
        )

        SharedAcademicProgramKnowledgeArea.objects.create(
            academic_program=cls.academic_program,
            knowledge_area=cls.knowledge_area,
            created_by=cls.system,
        )

        cls.syntax = platform_models.ValidSintaxis.objects.create(
            name="sintaxis journal api",
            booleans=["AND", "OR"],
            parenthesis=True,
            fields={"title": "ti"},
            created_by=cls.system,
        )
        cls.platform = Platform.objects.create(
            name="Scopus API Test",
            is_harvestable=True,
            base_api_url="https://api.scopus.test",
            url_image="https://example.org/scopus.png",
            valid_sintaxis=cls.syntax,
            status=Platform.Status.PUBLICADO,
            created_by=cls.system,
        )
        section_links = (
            (platform_models.SharedPlatformSupport, "institution", Institution.objects.create(name="UFPS", created_by=cls.system)),
            (platform_models.SharedPlatformLanguage, "language", cls.language),
            (platform_models.SharedPlatformCountry, "country", cls.country),
            (platform_models.SharedPlatformKnowledgeArea, "knowledge_area", cls.knowledge_area),
            (platform_models.SharedPlatformMaterialType, "material_type", cls.material_type),
            (platform_models.SharedPlatformAcademicProgram, "academic_program", cls.academic_program),
        )
        for through, field, value in section_links:
            through.objects.create(
                platform=cls.platform,
                **{field: value},
                created_by=cls.system,
            )
        platform_models.LinkCheckLog.objects.create(
            platform=cls.platform,
            url="https://example.org/scopus",
            is_active=True,
            last_check=timezone.now(),
            created_by=cls.system,
        )
        cls.license = models.License.objects.create(name="CC BY", created_by=cls.system)

    def setUp(self):
        self.client.force_authenticate(user=self.system)

    def _get_data(
        self,
        response: Any,
    ) -> dict[str, Any]:
        return getattr(response, "data", {})

    def _create_journal(
        self,
        *,
        issn="1234-5678",
        title="Journal API Test",
        active=True,
        validated=False,
    ):
        journal = models.Journal.objects.create(
            issn=issn,
            title=title,
            editorial=self.editorial,
            active=active,
            created_by=self.system,
        )

        if validated:
            journal.validated_by = self.system
            journal.validated_at = journal.created_at
            journal.save(
                update_fields=[
                    "validated_by",
                    "validated_at",
                ]
            )

        return journal

    def _complete_for_publication(self, journal):
        journal.publication_date = "2020-01-01"
        journal.save(update_fields=["publication_date"])
        specs = (
            (models.SharedJournalLanguage, "language", self.language),
            (models.SharedJournalCountry, "country", self.country),
            (models.SharedJournalKnowledgeArea, "knowledge_area", self.knowledge_area),
            (models.SharedJournalMaterialType, "material_type", self.material_type),
            (models.SharedJournalAcademicProgram, "academic_program", self.academic_program),
            (models.SharedJournalPlatform, "platform", self.platform),
            (models.SharedJournalLicense, "license", self.license),
        )
        for through, field, value in specs:
            defaults = {"created_by": self.system}
            if through is models.SharedJournalKnowledgeArea:
                defaults["is_derived"] = True
            through.objects.get_or_create(
                journal=journal,
                **{field: value},
                defaults=defaults,
            )

    # ==========================================================================
    # CRUD ADMINISTRATIVO
    # ==========================================================================

    def test_create_journal_endpoint(self):
        """
        POST /api/journals/ crea una revista correctamente.
        """
        response = self.client.post(
            "/api/journals/",
            {
                "issn": "1476 4687",
                "title": "Nature",
                "editorial": self.editorial.pk,
                "publication_date": "1869-11-04",
                "has_apc": False,
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/nature",
                }],
            },
            format="json",
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            201,
        )

        self.assertEqual(
            data["issn"],
            "1476-4687",
        )

        self.assertEqual(
            data["title"],
            "Nature",
        )

        self.assertIn(
            "created_by",
            data,
        )

        self.assertEqual(
            data["created_by"],
            self.system.pk,
        )

        self.assertFalse(data["active"])
        self.assertIsNone(data["validated_by"])
        self.assertIsNone(data["validated_at"])

    def test_create_cannot_publish_with_read_only_fields(self):
        response = self.client.post(
            "/api/journals/",
            {
                "issn": "1476-4690",
                "title": "Journal no publicada",
                "active": True,
                "validated_by": self.system.pk,
                "validated_at": "2026-10-09T12:00:00Z",
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/unpublished",
                }],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        journal = models.Journal.objects.get(pk=self._get_data(response)["id"])
        self.assertFalse(journal.active)
        self.assertIsNone(journal.validated_by)
        self.assertIsNone(journal.validated_at)

    def test_patch_cannot_control_publication_fields(self):
        journal = self._create_journal(active=False, validated=False)

        response = self.client.patch(
            f"/api/journals/{journal.pk}/",
            {
                "active": True,
                "validated_by": self.system.pk,
                "validated_at": "2026-10-09T12:00:00Z",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        journal.refresh_from_db()
        self.assertFalse(journal.active)
        self.assertIsNone(journal.validated_by)
        self.assertIsNone(journal.validated_at)

    def test_create_journal_endpoint_derives_knowledge_areas(self):
        manual_area = KnowledgeArea.objects.create(
            name="Ecología aplicada",
            created_by=self.system,
        )
        response = self.client.post(
            "/api/journals/",
            {
                "issn": "1476-4688",
                "title": "Nature Derived",
                "academic_programs": [self.academic_program.pk],
                "knowledge_areas": [manual_area.pk],
                "platforms": [{
                    "platform": self.platform.pk,
                    "journal_url": "https://8.8.8.8/nature-derived",
                }],
            },
            format="json",
        )

        data = self._get_data(response)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            {item["id"] for item in data["knowledge_areas"]},
            {self.knowledge_area.pk, manual_area.pk},
        )
        by_id = {item["id"]: item for item in data["knowledge_areas"]}
        self.assertTrue(by_id[self.knowledge_area.pk]["is_derived"])
        self.assertFalse(by_id[self.knowledge_area.pk]["editable"])
        self.assertTrue(by_id[manual_area.pk]["is_manual"])
        self.assertTrue(by_id[manual_area.pk]["editable"])

    def test_create_journal_endpoint_allows_draft_platform(self):
        draft_platform = Platform.objects.create(
            name="Draft API Platform",
            status=Platform.Status.BORRADOR,
            created_by=self.system,
        )

        response = self.client.post(
            "/api/journals/",
            {
                "issn": "1476-4689",
                "title": "Journal Draft Platform",
                "platforms": [
                    {
                        "platform": draft_platform.pk,
                        "journal_url": "https://8.8.8.8/draft-journal",
                    }
                ],
            },
            format="json",
        )

        data = self._get_data(response)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            models.SharedJournalPlatform.objects.filter(
                journal_id=data["id"],
                platform=draft_platform,
            ).exists()
        )
        draft_platform.refresh_from_db()
        self.assertEqual(draft_platform.status, Platform.Status.BORRADOR)
        self.assertIsNone(draft_platform.validated_by)
        self.assertIsNone(draft_platform.validated_at)

    def test_list_journals_returns_active_journals(self):
        """
        GET /api/journals/ lista las revistas no eliminadas.
        """
        journal_a = self._create_journal(
            issn="1111-1111",
            title="Journal A",
        )

        journal_b = self._create_journal(
            issn="2222-2222",
            title="Journal B",
        )

        archived = self._create_journal(
            issn="3333-3333",
            title="Journal Archived",
        )

        archived.soft_delete(
            user=self.system,
            explanation="Archivada para prueba",
        )

        response = self.client.get(
            "/api/journals/"
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            journal_a.pk,
            ids,
        )

        self.assertIn(
            journal_b.pk,
            ids,
        )

        self.assertNotIn(
            archived.pk,
            ids,
        )

    # ==========================================================================
    # PUBLICACIÓN
    # ==========================================================================

    def test_publish_action_endpoint(self):
        """
        POST /api/journals/{id}/publish/
        activa y valida la revista.
        """
        journal = self._create_journal(
            issn="4444-4444",
            title="Journal Publish",
            active=False,
            validated=False,
        )
        self._complete_for_publication(journal)

        response = self.client.post(
            f"/api/journals/{journal.pk}/publish/",
            {},
            format="json",
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        journal.refresh_from_db()

        self.assertTrue(
            journal.active
        )

        self.assertEqual(
            journal.validated_by_id,
            self.system.pk,
        )
        self.assertIsNotNone(journal.validated_at)

        public_response = self.client.get("/api/journals/public/")
        public_ids = [
            item["id"] for item in self._get_data(public_response)["results"]
        ]
        self.assertIn(journal.pk, public_ids)

        self.assertEqual(
            data["id"],
            journal.pk,
        )

    def test_publish_accepts_manual_effective_knowledge_area(self):
        journal = self._create_journal(
            issn="4545-4545",
            title="Journal Manual Area Publish",
            active=False,
            validated=False,
        )
        self._complete_for_publication(journal)
        area_link = models.SharedJournalKnowledgeArea.objects.get(
            journal=journal,
            knowledge_area=self.knowledge_area,
        )
        area_link.is_manual = True
        area_link.is_derived = False
        area_link.save(update_fields=["is_manual", "is_derived"])

        response = self.client.post(
            f"/api/journals/{journal.pk}/publish/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_deactivate_action_endpoint(self):
        """
        POST /api/journals/{id}/deactivate/
        desactiva una revista.
        """
        journal = self._create_journal(
            issn="5555-5555",
            title="Journal Deactivate",
            active=True,
            validated=True,
        )
        self._complete_for_publication(journal)

        response = self.client.post(
            f"/api/journals/{journal.pk}/deactivate/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        journal.refresh_from_db()

        self.assertFalse(
            journal.active
        )

        self.assertEqual(
            journal.validated_by_id,
            self.system.pk,
        )
        self.assertIsNotNone(journal.validated_at)

        public_response = self.client.get("/api/journals/public/")
        public_ids = [
            item["id"] for item in self._get_data(public_response)["results"]
        ]
        self.assertNotIn(journal.pk, public_ids)

    # ==========================================================================
    # INVALIDACIÓN Y REPUBLICACIÓN
    # ==========================================================================

    def test_edit_invalidates_and_republish_restores_public_visibility(self):
        journal = self._create_journal(
            issn="4545-4545",
            active=True,
            validated=True,
        )
        self._complete_for_publication(journal)

        response = self.client.patch(
            f"/api/journals/{journal.pk}/",
            {"title": "Journal revisado"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        journal.refresh_from_db()
        self.assertFalse(journal.active)
        self.assertIsNone(journal.validated_by)
        self.assertIsNone(journal.validated_at)

        public_response = self.client.get("/api/journals/public/")
        public_ids = [
            item["id"] for item in self._get_data(public_response)["results"]
        ]
        self.assertNotIn(journal.pk, public_ids)

        publish_response = self.client.post(
            f"/api/journals/{journal.pk}/publish/",
            {},
            format="json",
        )

        self.assertEqual(publish_response.status_code, 200)
        journal.refresh_from_db()
        self.assertTrue(journal.active)
        self.assertEqual(journal.validated_by_id, self.system.pk)
        self.assertIsNotNone(journal.validated_at)

        public_response = self.client.get("/api/journals/public/")
        public_ids = [
            item["id"] for item in self._get_data(public_response)["results"]
        ]
        self.assertIn(journal.pk, public_ids)

    # ===========================================================================
    # SOFT DELETE / ARCHIVED / RESTORE
    # ===========================================================================

    def test_destroy_with_business_relation_soft_deletes_journal(self):
        """
        Una revista con relaciones de negocio se elimina mediante
        Soft Delete y requiere explicación.
        """
        journal = self._create_journal(
            issn="6666-6666",
            title="Journal Delete",
        )

        models.SharedJournalKnowledgeArea.objects.create(
            journal=journal,
            knowledge_area=self.knowledge_area,
            is_manual=True,
            created_by=self.system,
        )

        response = self.client.delete(
            f"/api/journals/{journal.pk}/",
            {
                "delete_explanation": (
                    "Eliminación lógica para prueba."
                )
            },
            format="json",
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertFalse(
            models.Journal.objects.filter(
                pk=journal.pk
            ).exists()
        )

        self.assertTrue(
            models.Journal.all_objects.filter(
                pk=journal.pk
            ).exists()
        )

        self.assertEqual(
            data["permanent"],
            False,
        )

    def test_archived_endpoint_returns_deleted_journals(self):
        """
        GET /api/journals/archived/
        devuelve revistas eliminadas.
        """
        journal = self._create_journal(
            issn="7777-7777",
            title="Journal Archived API",
        )

        journal.soft_delete(
            user=self.system,
            explanation="Test archivado",
        )

        response = self.client.get(
            "/api/journals/archived/"
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        archived_ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            journal.pk,
            archived_ids,
        )

    def test_restore_action_endpoint(self):
        """
        POST /api/journals/{id}/restore/
        restaura una revista eliminada y limpia su validación.
        """
        journal = self._create_journal(
            issn="8888-8888",
            title="Journal Restore API",
            active=True,
            validated=True,
        )
        self._complete_for_publication(journal)

        journal.soft_delete(
            user=self.system,
            explanation="Eliminada para restauración.",
        )

        response = self.client.post(
            f"/api/journals/{journal.pk}/restore/",
            {},
            format="json",
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        journal.refresh_from_db()

        self.assertFalse(
            journal.is_deleted
        )

        self.assertFalse(
            journal.active
        )

        self.assertIsNone(
            journal.validated_by
        )

        self.assertIsNone(
            journal.validated_at
        )

        self.assertEqual(
            data["id"],
            journal.pk,
        )

        public_response = self.client.get("/api/journals/public/")
        public_ids = [
            item["id"] for item in self._get_data(public_response)["results"]
        ]
        self.assertNotIn(journal.pk, public_ids)

        publish_response = self.client.post(
            f"/api/journals/{journal.pk}/publish/",
            {},
            format="json",
        )
        self.assertEqual(publish_response.status_code, 200)

        public_response = self.client.get("/api/journals/public/")
        public_ids = [
            item["id"] for item in self._get_data(public_response)["results"]
        ]
        self.assertIn(journal.pk, public_ids)

    def test_restore_nonexistent_archived_journal_returns_404(self):
        """
        Restaurar una revista inexistente debe devolver 404.
        """
        response = self.client.post(
            "/api/journals/999999/restore/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    # ==========================================================================
    # API PÚBLICA
    # ==========================================================================

    def test_public_endpoint_lists_only_active_validated_journals(self):
        """
        GET /api/journals/public/ solamente expone revistas
        activas y validadas.
        """
        public_journal = self._create_journal(
            issn="1010-1010",
            title="Public Journal",
            active=True,
            validated=True,
        )

        inactive_journal = self._create_journal(
            issn="2020-2020",
            title="Inactive Journal",
            active=False,
            validated=True,
        )

        unvalidated_journal = self._create_journal(
            issn="3030-3030",
            title="Unvalidated Journal",
            active=True,
            validated=False,
        )

        response = self.client.get(
            "/api/journals/public/"
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            public_journal.pk,
            ids,
        )

        self.assertNotIn(
            inactive_journal.pk,
            ids,
        )

        self.assertNotIn(
            unvalidated_journal.pk,
            ids,
        )

    def test_public_endpoint_excludes_soft_deleted_journals(self):
        """
        Una revista eliminada no aparece en la API pública.
        """
        journal = self._create_journal(
            issn="4040-4040",
            title="Deleted Public Journal",
            active=True,
            validated=True,
        )

        journal.soft_delete(
            user=self.system,
            explanation="Eliminada para prueba",
        )

        response = self.client.get(
            "/api/journals/public/"
        )

        data = self._get_data(response)

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertNotIn(
            journal.pk,
            ids,
        )

    # ==========================================================================
    # FILTROS PÚBLICOS
    # ==========================================================================

    def test_public_filter_by_knowledge_area(self):
        """
        Filtra revistas públicas por área del conocimiento.
        """
        journal = self._create_journal(
            issn="5050-5050",
            title="Knowledge Area Journal",
            validated=True,
        )

        models.SharedJournalKnowledgeArea.objects.create(
            journal=journal,
            knowledge_area=self.knowledge_area,
            is_derived=True,
            created_by=self.system,
        )

        response = self.client.get(
            "/api/journals/public/",
            {
                "knowledge_area": self.knowledge_area.pk,
            },
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            journal.pk,
            ids,
        )

    def test_public_filter_by_country(self):
        """
        Filtra revistas públicas por país.
        """
        journal = self._create_journal(
            issn="6060-6060",
            title="Country Journal",
            validated=True,
        )

        models.SharedJournalCountry.objects.create(
            journal=journal,
            country=self.country,
            created_by=self.system,
        )

        response = self.client.get(
            "/api/journals/public/",
            {
                "country": self.country.pk,
            },
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            journal.pk,
            ids,
        )

    def test_public_filter_by_language(self):
        """
        Filtra revistas públicas por idioma.
        """
        journal = self._create_journal(
            issn="7070-7070",
            title="Language Journal",
            validated=True,
        )

        models.SharedJournalLanguage.objects.create(
            journal=journal,
            language=self.language,
            created_by=self.system,
        )

        response = self.client.get(
            "/api/journals/public/",
            {
                "language": self.language.pk,
            },
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            journal.pk,
            ids,
        )

    def test_public_filter_by_platform(self):
        """
        Filtra revistas públicas por plataforma.
        """
        journal = self._create_journal(
            issn="8080-8080",
            title="Platform Journal",
            validated=True,
        )

        models.SharedJournalPlatform.objects.create(
            journal=journal,
            platform=self.platform,
            created_by=self.system,
        )

        response = self.client.get(
            "/api/journals/public/",
            {
                "platform": self.platform.pk,
            },
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            journal.pk,
            ids,
        )

    def test_public_filter_by_title(self):
        """
        Filtra revistas públicas por coincidencia parcial del título.
        """
        journal = self._create_journal(
            issn="9090-9090",
            title="International Journal of Biology",
            validated=True,
        )

        response = self.client.get(
            "/api/journals/public/",
            {
                "title": "Biology",
            },
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            journal.pk,
            ids,
        )

    def test_public_filter_by_issn_without_hyphen(self):
        """
        El filtro ISSN acepta el valor con o sin guion.
        """
        journal = self._create_journal(
            issn="1234-5678",
            title="ISSN Filter Journal",
            validated=True,
        )

        response = self.client.get(
            "/api/journals/public/",
            {
                "issn": "12345678",
            },
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        ids = [
            item["id"]
            for item in data["results"]
        ]

        self.assertIn(
            journal.pk,
            ids,
        )

    def test_public_filter_with_nonexistent_knowledge_area_returns_empty(self):
        """
        Un área del conocimiento inexistente no genera error
        y retorna cero resultados.
        """
        response = self.client.get(
            "/api/journals/public/",
            {
                "knowledge_area": 999999,
            },
        )

        data = self._get_data(response)

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            data["total_items"],
            0,
        )

    def test_knowledge_area_catalog_filters_by_journal_origin(self):
        journal = self._create_journal(issn="6060-6060", active=False)
        manual = KnowledgeArea.objects.create(
            name="Área manual filtro", created_by=self.system
        )
        derived = KnowledgeArea.objects.create(
            name="Área derivada filtro", created_by=self.system
        )
        both = KnowledgeArea.objects.create(
            name="Área mixta filtro", created_by=self.system
        )
        available = KnowledgeArea.objects.create(
            name="Área disponible filtro", created_by=self.system
        )
        for area, is_manual, is_derived in (
            (manual, True, False),
            (derived, False, True),
            (both, True, True),
        ):
            models.SharedJournalKnowledgeArea.objects.create(
                journal=journal,
                knowledge_area=area,
                is_manual=is_manual,
                is_derived=is_derived,
                created_by=self.system,
            )

        cases = {
            "manual": manual.pk,
            "derived": derived.pk,
            "both": both.pk,
        }
        for origin, expected_id in cases.items():
            response = self.client.get(
                "/api/catalog/knowledge-areas/",
                {"journal": journal.pk, "origin": origin},
            )
            data = self._get_data(response)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                {item["id"] for item in data["results"]}, {expected_id}
            )

        editable_response = self.client.get(
            "/api/catalog/knowledge-areas/",
            {"journal": journal.pk, "editable": "true"},
        )
        self.assertEqual(
            {item["id"] for item in self._get_data(editable_response)["results"]},
            {manual.pk},
        )

        available_response = self.client.get(
            "/api/catalog/knowledge-areas/",
            {
                "available_for_journal": journal.pk,
                "page_size": 100,
            },
        )
        self.assertEqual(available_response.status_code, 200)
        available_ids = {
            item["id"]
            for item in self._get_data(available_response)["results"]
        }
        self.assertIn(available.pk, available_ids)
        self.assertNotIn(manual.pk, available_ids)
        self.assertNotIn(derived.pk, available_ids)
        self.assertNotIn(both.pk, available_ids)
