from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.account.models import User


class CookieSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            email="session@example.com",
            password="A-strong-test-password-927",
            full_name="Cuenta de prueba",
        )

    def login(self, client):
        csrf = client.get("/api/accounts/auth/csrf/")
        token = csrf.cookies["csrftoken"].value
        return client.post(
            "/api/accounts/auth/login/",
            {
                "email": self.user.email,
                "password": "A-strong-test-password-927",
            },
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

    def test_login_requires_csrf_and_establishes_session_cookie(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.post(
            "/api/accounts/auth/login/",
            {
                "email": self.user.email,
                "password": "A-strong-test-password-927",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        response = self.login(client)
        self.assertEqual(response.status_code, 200)
        self.assertIn("sessionid", response.cookies)
        self.assertTrue(response.cookies["sessionid"]["httponly"])
        self.assertEqual(response.cookies["sessionid"]["max-age"], 15 * 60)
        self.assertTrue(response.data["user"]["is_superadmin"])

    def test_authenticated_activity_renews_the_session_expiration(self):
        client = APIClient()
        self.login(client)
        session_key = client.cookies["sessionid"].value
        expiring_soon = timezone.now() + timedelta(minutes=1)
        Session.objects.filter(session_key=session_key).update(
            expire_date=expiring_soon,
        )

        response = client.get("/api/accounts/auth/me/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.cookies["sessionid"].value, session_key)
        renewed_session = Session.objects.get(session_key=session_key)
        self.assertGreater(
            renewed_session.expire_date,
            expiring_soon + timedelta(minutes=13),
        )
        self.assertEqual(response.cookies["sessionid"]["max-age"], 15 * 60)

    def test_a_second_login_terminates_and_notifies_the_first_session(self):
        first_client = APIClient()
        second_client = APIClient()
        first_response = self.login(first_client)
        second_response = self.login(second_client)
        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(second_response.data["previous_session_terminated"])
        old_session_response = first_client.get("/api/accounts/auth/me/")
        self.assertEqual(old_session_response.status_code, 401)
        self.assertIn("otro lugar", old_session_response.data["detail"])

    def test_temporary_password_blocks_private_routes_until_changed(self):
        user = User.objects.create_user(
            email="invited@example.com",
            password="Temporary-test-password-28",
            full_name="Cuenta invitada",
            force_password_change=True,
        )
        client = APIClient()
        csrf = client.get("/api/accounts/auth/csrf/")
        response = client.post(
            "/api/accounts/auth/login/",
            {
                "email": user.email,
                "password": "Temporary-test-password-28",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["must_change_password"])
        self.assertEqual(client.get("/api/audit/logs/").status_code, 403)
        self.assertEqual(
            client.patch(
                "/api/accounts/auth/me/",
                {"full_name": "Nombre nuevo"},
                format="json",
            ).status_code,
            403,
        )

        response = client.post(
            "/api/accounts/password/change/",
            {
                "current_password": "Temporary-test-password-28",
                "new_password": "Changed-test-password-947",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.force_password_change)
        self.assertEqual(client.get("/api/accounts/auth/me/").status_code, 200)


class AccountRestoreTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-restore@example.com",
            password="A-strong-admin-password-927",
            full_name="Admin",
        )
        self.account = User.objects.create_user(
            email="deleted@example.com",
            password="A-strong-user-password-927",
            full_name="Cuenta desactivada",
            created_by=self.admin,
        )
        self.account.soft_delete(self.admin, "Desactivada para prueba")
        self.account.is_active = False
        self.account.save(update_fields=["is_active"])
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_restore_reactivates_the_account_and_keeps_audit_actor(self):
        archived_response = self.client.get("/api/accounts/users/archived/")
        self.assertEqual(archived_response.status_code, 200)
        self.assertEqual(archived_response.data[0]["id"], self.account.pk)

        response = self.client.post(
            f"/api/accounts/users/{self.account.pk}/restore/",
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)
        self.assertIsNone(self.account.deleted_at)
        self.assertIsNone(self.account.delete_explanation)
        self.assertEqual(self.account.updated_by, self.admin)
        self.assertIn("effective_permissions", response.data)

    def test_restore_rejects_an_already_active_account(self):
        self.account.restore()
        self.account.is_active = True
        self.account.save(update_fields=["is_active"])

        response = self.client.post(
            f"/api/accounts/users/{self.account.pk}/restore/",
            format="json",
        )

        self.assertEqual(response.status_code, 400)
