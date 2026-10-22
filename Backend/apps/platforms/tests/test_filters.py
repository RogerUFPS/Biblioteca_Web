from rest_framework.test import APITestCase

from apps.account.models import User
from apps.catalog.models import (
    AcademicProgram,
    Country,
    Institution,
    KnowledgeArea,
    Language,
    MaterialType,
)

from apps.platforms import models


class PlatformFilterTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            code=0,
            full_name="Sistema filtros Platform",
            email="platform-filters@test.local",
            is_superadmin=True,
        )
        cls.institution = Institution.objects.create(
            name="Institución filtros",
            created_by=cls.user,
        )
        cls.country = Country.objects.create(
            name="País Platform filtros",
            abbreviation="pf",
            emoji_flag="🏳️",
            created_by=cls.user,
        )
        cls.language = Language.objects.create(
            name="Idioma Platform filtros",
            abbreviation="pf",
            created_by=cls.user,
        )
        cls.knowledge_area = KnowledgeArea.objects.create(
            name="Área Platform filtros",
            created_by=cls.user,
        )
        cls.material_type = MaterialType.objects.create(
            name="Material Platform filtros",
            created_by=cls.user,
        )
        cls.academic_program = AcademicProgram.objects.create(
            name="Programa Platform filtros",
            created_by=cls.user,
        )
        cls.syntax = models.ValidSintaxis.objects.create(
            name="Sintaxis filtros",
            created_by=cls.user,
        )

        cls.draft = cls._create_platform(
            name="Alpha Draft",
            status=models.Platform.Status.BORRADOR,
            is_harvestable=False,
            requires_registration=False,
            has_access_text=False,
        )
        cls.published = cls._create_platform(
            name="Beta Published",
            status=models.Platform.Status.PUBLICADO,
            is_harvestable=True,
            requires_registration=True,
            has_access_text=True,
        )
        cls.obsolete = cls._create_platform(
            name="Gamma Obsolete",
            status=models.Platform.Status.OBSOLETO,
            is_harvestable=False,
            requires_registration=False,
            has_access_text=False,
        )
        cls._add_relations(cls.published)
        cls._add_relations(cls.draft)

    @classmethod
    def _create_platform(cls, **kwargs):
        return models.Platform.objects.create(
            valid_sintaxis=cls.syntax,
            created_by=cls.user,
            **kwargs,
        )

    @classmethod
    def _add_relations(cls, platform):
        specs = (
            (models.SharedPlatformSupport, "institution", cls.institution),
            (models.SharedPlatformCountry, "country", cls.country),
            (models.SharedPlatformLanguage, "language", cls.language),
            (
                models.SharedPlatformKnowledgeArea,
                "knowledge_area",
                cls.knowledge_area,
            ),
            (models.SharedPlatformMaterialType, "material_type", cls.material_type),
            (
                models.SharedPlatformAcademicProgram,
                "academic_program",
                cls.academic_program,
            ),
        )
        for through_model, field_name, related in specs:
            through_model.objects.create(
                platform=platform,
                created_by=cls.user,
                **{field_name: related},
            )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    @staticmethod
    def _ids(response):
        return [item["id"] for item in response.data["results"]]

    def test_admin_status_filter_accepts_all_model_values(self):
        cases = (
            ("borrador", self.draft.pk),
            ("publicado", self.published.pk),
            ("obsoleto", self.obsolete.pk),
        )
        for status, expected_id in cases:
            with self.subTest(status=status):
                response = self.client.get(
                    "/api/platforms/",
                    {"status": status},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self._ids(response), [expected_id])

    def test_admin_boolean_and_syntax_filters(self):
        response = self.client.get(
            "/api/platforms/",
            {
                "is_harvestable": "true",
                "requires_registration": "true",
                "has_access_text": "true",
                "valid_sintaxis": self.syntax.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), [self.published.pk])

        false_response = self.client.get(
            "/api/platforms/",
            {"is_harvestable": "false"},
        )
        self.assertEqual(false_response.status_code, 200)
        self.assertEqual(
            set(self._ids(false_response)),
            {self.draft.pk, self.obsolete.pk},
        )

    def test_admin_supports_all_relational_filters(self):
        params = {
            "institution": self.institution.pk,
            "country": self.country.pk,
            "language": self.language.pk,
            "knowledge_area": self.knowledge_area.pk,
            "material_type": self.material_type.pk,
            "academic_program": self.academic_program.pk,
        }

        response = self.client.get("/api/platforms/", params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(self._ids(response)),
            {self.draft.pk, self.published.pk},
        )

    def test_public_supports_relational_and_boolean_filters(self):
        params = {
            "institution": self.institution.pk,
            "country": self.country.pk,
            "language": self.language.pk,
            "knowledge_area": self.knowledge_area.pk,
            "material_type": self.material_type.pk,
            "academic_program": self.academic_program.pk,
            "is_harvestable": "true",
            "requires_registration": "true",
            "has_access_text": "true",
        }

        response = self.client.get("/api/platforms/public/", params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), [self.published.pk])

    def test_public_filters_never_include_non_published_platforms(self):
        response = self.client.get(
            "/api/platforms/public/",
            {"institution": self.institution.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), [self.published.pk])

    def test_soft_deleted_relation_does_not_influence_filter(self):
        link = models.SharedPlatformSupport.objects.get(
            platform=self.published,
            institution=self.institution,
        )
        link.soft_delete(
            user=self.user,
            explanation="Validar filtros con Soft Delete",
        )

        response = self.client.get(
            "/api/platforms/public/",
            {"institution": self.institution.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), [])

    def test_soft_deleted_syntax_does_not_influence_admin_filter(self):
        self.syntax.soft_delete(
            user=self.user,
            explanation="Validar sintaxis eliminada",
        )

        response = self.client.get(
            "/api/platforms/",
            {"valid_sintaxis": self.syntax.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), [])

    def test_relational_joins_do_not_duplicate_results(self):
        response = self.client.get(
            "/api/platforms/public/",
            {
                "country": self.country.pk,
                "language": self.language.pk,
                "academic_program": self.academic_program.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(response), [self.published.pk])

    def test_invalid_status_is_rejected(self):
        response = self.client.get(
            "/api/platforms/",
            {"status": "PUBLICADO"},
        )

        self.assertEqual(response.status_code, 400)

    def test_search_ordering_and_pagination_apply_to_filtered_queryset(self):
        response = self.client.get(
            "/api/platforms/",
            {
                "search": "Published",
                "status": "publicado",
                "ordering": "-name",
                "page_size": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["page_size"], 1)
        self.assertEqual(self._ids(response), [self.published.pk])
