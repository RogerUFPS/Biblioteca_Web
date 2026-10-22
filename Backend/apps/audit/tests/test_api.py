from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase
from auditlog.models import LogEntry
from apps.account.models import User
from apps.audit.models import AuditLog
from apps.catalog.models import Institution, Language


class AuditAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create(
            code=0,
            full_name="Sistema",
            email="sistema@example.com",
            is_superadmin=True,
        )
        self.client.force_authenticate(user=self.user)
        AuditLog.objects.all().delete()
        self.inst_ct = ContentType.objects.get_for_model(Institution)
        self.lang_ct = ContentType.objects.get_for_model(Language)

        # Crear registros de prueba
        self.log_create = AuditLog.objects.create(
            action=LogEntry.Action.CREATE,
            content_type=self.inst_ct,
            object_pk="10",
            object_repr="UFPS",
            actor=self.user,
            changes={"name": ["", "ufps"]},
        )

        self.log_update = AuditLog.objects.create(
            action=LogEntry.Action.UPDATE,
            content_type=self.inst_ct,
            object_pk="10",
            object_repr="UFPS Colombia",
            actor=None,
            changes={"name": ["ufps", "ufps colombia"]},
        )

        self.log_delete = AuditLog.objects.create(
            action=LogEntry.Action.DELETE,
            content_type=self.lang_ct,
            object_pk="2",
            object_repr="Inglés (en)",
            actor=None,
            changes={"name": ["Inglés", ""]},
        )

    def test_list_audit_logs_with_pagination(self):
        response = self.client.get("/api/audit/logs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("current_page", data)
        self.assertIn("total_pages", data)
        self.assertIn("page_size", data)
        self.assertIn("total_items", data)
        self.assertIn("results", data)
        self.assertEqual(data["total_items"], 3)
        self.assertEqual(len(data["results"]), 3)

        first_item = data["results"][0]
        self.assertIn("item_number", first_item)
        self.assertIn("action", first_item)
        self.assertIn("action_name", first_item)
        self.assertIn("action_display", first_item)
        self.assertIn("resource", first_item)
        self.assertIn("object_id", first_item)
        self.assertIn("changes", first_item)

    def test_retrieve_audit_log_detail(self):
        response = self.client.get(f"/api/audit/logs/{self.log_create.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], self.log_create.id)
        self.assertEqual(data["action"], LogEntry.Action.CREATE)
        self.assertEqual(data["action_name"], "create")
        self.assertEqual(data["action_display"], "Creación")
        self.assertEqual(data["resource"], "institution")
        self.assertEqual(data["object_id"], "10")
        self.assertIsNotNone(data["actor_detail"])
        self.assertEqual(data["actor_detail"]["code"], 0)
        self.assertEqual(data["actor_detail"]["full_name"], "Sistema")

    def test_retrieve_unauthenticated_log_has_null_actor(self):
        response = self.client.get(f"/api/audit/logs/{self.log_update.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIsNone(data["actor"])
        self.assertIsNone(data["actor_name"])
        self.assertIsNone(data["actor_detail"])

    def test_immutability_endpoints_rejected(self):
        """Verifica que POST, PUT, PATCH y DELETE respondan 405 Method Not Allowed."""
        # Creación no permitida
        create_res = self.client.post("/api/audit/logs/", {"action": 0})
        self.assertEqual(create_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Modificación no permitida
        put_res = self.client.put(f"/api/audit/logs/{self.log_create.id}/", {"object_repr": "fake"})
        self.assertEqual(put_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        patch_res = self.client.patch(f"/api/audit/logs/{self.log_create.id}/", {"object_repr": "fake"})
        self.assertEqual(patch_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        # Eliminación no permitida
        del_res = self.client.delete(f"/api/audit/logs/{self.log_create.id}/")
        self.assertEqual(del_res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_filter_by_action(self):
        response = self.client.get("/api/audit/logs/?action=0")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.log_create.id)

        response_name = self.client.get("/api/audit/logs/?action_name=delete")
        self.assertEqual(response_name.status_code, status.HTTP_200_OK)
        results_del = response_name.json()["results"]
        self.assertEqual(len(results_del), 1)
        self.assertEqual(results_del[0]["id"], self.log_delete.id)

    def test_filter_by_resource(self):
        response = self.client.get("/api/audit/logs/?resource=institution")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["resource"], "institution")

    def test_filter_by_object_id(self):
        response = self.client.get("/api/audit/logs/?object_id=10")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)

    def test_filter_by_is_anonymous(self):
        response_anon = self.client.get("/api/audit/logs/?is_anonymous=true")
        self.assertEqual(response_anon.status_code, status.HTTP_200_OK)
        results_anon = response_anon.json()["results"]
        self.assertEqual(len(results_anon), 2)

        response_auth = self.client.get(
            "/api/audit/logs/?is_anonymous=false&action=0"
        )
        self.assertEqual(response_auth.status_code, status.HTTP_200_OK)
        results_auth = response_auth.json()["results"]
        self.assertEqual(len(results_auth), 1)
        self.assertEqual(results_auth[0]["id"], self.log_create.id)

    def test_search_filter(self):
        response = self.client.get("/api/audit/logs/?search=Inglés")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.log_delete.id)

    def test_resources_catalog_endpoint(self):
        response = self.client.get("/api/audit/logs/resources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        first = data[0]
        self.assertIn("resource", first)
        self.assertIn("label", first)
        self.assertIn("app", first)
        self.assertIn("content_type_id", first)

    def test_actions_catalog_endpoint(self):
        response = self.client.get("/api/audit/logs/actions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 4)
        action_names = [a["name"] for a in data]
        self.assertIn("create", action_names)
        self.assertIn("update", action_names)
        self.assertIn("delete", action_names)
