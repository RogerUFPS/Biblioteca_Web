from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase

from apps.account.permissions import ApplicationPermission, normalize_permissions


class ApplicationPermissionTests(SimpleTestCase):
    def setUp(self):
        self.permission = ApplicationPermission()
        self.factory = RequestFactory()
        self.anonymous = SimpleNamespace(is_authenticated=False)

    def allowed(self, method, path, user=None):
        request = getattr(self.factory, method.lower())(path)
        request.user = user or self.anonymous
        return self.permission.has_permission(request, None)

    def test_catalog_get_and_public_routes_are_public_read_only(self):
        self.assertTrue(self.allowed("get", "/api/catalog/knowledge-areas/"))
        self.assertTrue(self.allowed("get", "/api/journals/public/"))
        self.assertTrue(self.allowed("get", "/api/platforms/public/"))
        self.assertFalse(self.allowed("post", "/api/catalog/knowledge-areas/"))
        self.assertFalse(self.allowed("post", "/api/journals/public/"))
        self.assertFalse(self.allowed("get", "/api/journals/"))

    def test_granting_a_write_permission_also_grants_view(self):
        permissions = normalize_permissions({
            "catalog": {"knowledge-areas": {"update": True}},
        })
        self.assertTrue(permissions["catalog"]["knowledge-areas"]["view"])
        user = SimpleNamespace(
            is_authenticated=True,
            is_superadmin=False,
            force_password_change=False,
            effective_permissions=lambda: permissions,
        )
        self.assertFalse(self.allowed("get", "/api/audit/logs/", user=user))
        self.assertTrue(
            self.allowed("patch", "/api/catalog/knowledge-areas/7/", user=user)
        )
        self.assertTrue(
            self.allowed("get", "/api/catalog/knowledge-areas/", user=user)
        )
        self.assertFalse(
            self.allowed("post", "/api/catalog/knowledge-areas/7/restore/", user=user)
        )

    def test_special_actions_need_their_own_grant(self):
        permissions = {
            "journals": {"journals": {"view": True, "update": True}},
        }
        user = SimpleNamespace(
            is_authenticated=True,
            is_superadmin=False,
            force_password_change=False,
            effective_permissions=lambda: permissions,
        )
        self.assertFalse(
            self.allowed("post", "/api/journals/7/publish/", user=user)
        )
        permissions["journals"]["journals"]["publish"] = True
        self.assertTrue(
            self.allowed("post", "/api/journals/7/publish/", user=user)
        )

    def test_user_restore_requires_restore_permission(self):
        permissions = {
            "accounts": {"users": {"view": True, "delete": True}},
        }
        user = SimpleNamespace(
            is_authenticated=True,
            is_superadmin=False,
            force_password_change=False,
            effective_permissions=lambda: permissions,
        )
        self.assertFalse(
            self.allowed("post", "/api/accounts/users/7/restore/", user=user)
        )
        permissions["accounts"]["users"]["restore"] = True
        self.assertTrue(
            self.allowed("post", "/api/accounts/users/7/restore/", user=user)
        )

    def test_run_due_is_public_only_for_its_post_route(self):
        self.assertTrue(
            self.allowed("post", "/api/harvesting/schedules/run-due/")
        )
        self.assertFalse(
            self.allowed("get", "/api/harvesting/schedules/run-due/")
        )
        self.assertFalse(
            self.allowed("post", "/api/harvesting/schedules/")
        )

    def test_permissions_reject_unknown_actions_and_non_boolean_values(self):
        with self.assertRaises(ValueError):
            normalize_permissions({
                "catalog": {"knowledge-areas": {"publish": True}},
            })
        with self.assertRaises(ValueError):
            normalize_permissions({
                "catalog": {"knowledge-areas": {"update": "yes"}},
            })
