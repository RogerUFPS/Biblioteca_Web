from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from auditlog.models import LogEntry
from apps.account.models import User
from apps.audit.models import AuditLog
from apps.catalog.models import Institution


class AuditLogModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            code=0,
            full_name="Sistema",
            email="sistema@example.com",
        )
        self.institution_ct = ContentType.objects.get_for_model(Institution)

    def test_audit_log_creation_and_properties(self):
        log = AuditLog.objects.create(
            action=LogEntry.Action.CREATE,
            content_type=self.institution_ct,
            object_pk="1",
            object_repr="UFPS",
            actor=self.user,
            changes={"name": ["", "ufps"]},
        )

        self.assertEqual(log.action_name, "create")
        self.assertEqual(log.action_display, "Creación")
        self.assertEqual(log.resource, "institution")
        self.assertEqual(log.resource_display, "institution")
        self.assertFalse(log.is_soft_delete)
        self.assertFalse(log.is_restore)

    def test_audit_log_immutability_on_update(self):
        log = AuditLog.objects.create(
            action=LogEntry.Action.CREATE,
            content_type=self.institution_ct,
            object_pk="1",
            object_repr="UFPS",
            actor=None,
            changes={"name": ["", "ufps"]},
        )

        log.object_repr = "Modificado"
        with self.assertRaises(PermissionDenied):
            log.save()

    def test_audit_log_immutability_on_delete(self):
        log = AuditLog.objects.create(
            action=LogEntry.Action.CREATE,
            content_type=self.institution_ct,
            object_pk="1",
            object_repr="UFPS",
            actor=None,
            changes={"name": ["", "ufps"]},
        )

        with self.assertRaises(PermissionDenied):
            log.delete()

    def test_audit_log_soft_delete_and_restore_detection(self):
        soft_delete_log = AuditLog.objects.create(
            action=LogEntry.Action.UPDATE,
            content_type=self.institution_ct,
            object_pk="1",
            object_repr="UFPS",
            changes={"deleted_at": [None, "2026-10-08T20:00:00Z"]},
        )
        self.assertTrue(soft_delete_log.is_soft_delete)
        self.assertFalse(soft_delete_log.is_restore)

        restore_log = AuditLog.objects.create(
            action=LogEntry.Action.UPDATE,
            content_type=self.institution_ct,
            object_pk="1",
            object_repr="UFPS",
            changes={"deleted_at": ["2026-10-08T20:00:00Z", None]},
        )
        self.assertFalse(restore_log.is_soft_delete)
        self.assertTrue(restore_log.is_restore)
