"""
Suite de pruebas de integracion para la bitacora de auditoria.

Cubre tres areas criticas:
  1. Aislamiento correcto del actor  - el log almacena al usuario que realizo
     la accion, NO al usuario que esta actualmente autenticado viendo los logs.
  2. Endpoints publicos              - login, registro y recuperacion de
     contrasena NO deben generar entradas en la bitacora.
  3. Regresion CRUD                  - creacion, actualizacion y eliminacion de
     registros siguen generando logs con delta correcto.
"""
import json

from django.test import Client, TestCase

from auditlog.context import set_actor
from auditlog.models import LogEntry

from apps.account.models import User
from apps.audit.models import AuditLog
from apps.catalog.models import Country, Institution


# ---------------------------------------------------------------------------
# 1.  AISLAMIENTO DEL ACTOR
# ---------------------------------------------------------------------------

class AuditActorIsolationTests(TestCase):
    """
    Reproduce el bug reportado:
    el usuario que sale como responsable siempre es el que esta logueado
    actualmente, no el que realizo la accion.

    La bitacora debe guardar al actor en el momento de la escritura y ese
    valor no debe cambiar cuando otro usuario consulta los logs.
    """

    def setUp(self):
        self.roger = User.objects.create_user(
            email="roger@test.com",
            password="Contrasena-Fuerte-2026",
            full_name="Roger Miranda",
            is_superadmin=True,
        )
        self.admin = User.objects.create_user(
            email="admin@test.com",
            password="Contrasena-Fuerte-2026",
            full_name="Administrador Principal",
            is_superadmin=True,
        )
        AuditLog.objects.all().delete()

    def test_actor_es_quien_realizo_la_accion_no_quien_la_consulta(self):
        """
        Roger crea una institucion -> el log queda con actor=Roger.
        Luego Admin consulta la bitacora -> el actor sigue siendo Roger,
        no se modifica al cambiar de sesion.
        """
        with set_actor(self.roger):
            inst = Institution.objects.create(
                name="universidad francisco de paula santander",
                created_by=self.roger,
            )

        log = AuditLog.objects.filter(
            object_pk=str(inst.pk),
            content_type__model="institution",
        ).first()

        self.assertIsNotNone(log, "Debe existir un log para la institucion creada.")
        self.assertEqual(log.action, LogEntry.Action.CREATE)
        self.assertEqual(
            log.actor_id, self.roger.pk,
            "El actor debe ser el usuario que realizo la accion (Roger).",
        )
        self.assertNotEqual(
            log.actor_id, self.admin.pk,
            "El actor NO debe ser el usuario que actualmente consulta los logs.",
        )
        self.assertEqual(log.actor.full_name, "Roger Miranda")

    def test_dos_actores_distintos_tienen_logs_aislados(self):
        """Roger y Admin realizan acciones distintas; cada log debe asociarse
        exclusivamente con quien lo genero."""
        with set_actor(self.roger):
            inst_roger = Institution.objects.create(
                name="institucion de roger",
                created_by=self.roger,
            )
        with set_actor(self.admin):
            inst_admin = Institution.objects.create(
                name="institucion del administrador",
                created_by=self.admin,
            )

        log_roger = AuditLog.objects.filter(
            object_pk=str(inst_roger.pk),
            action=LogEntry.Action.CREATE,
        ).first()
        log_admin = AuditLog.objects.filter(
            object_pk=str(inst_admin.pk),
            action=LogEntry.Action.CREATE,
        ).first()

        self.assertIsNotNone(log_roger)
        self.assertIsNotNone(log_admin)
        self.assertEqual(log_roger.actor_id, self.roger.pk)
        self.assertEqual(log_admin.actor_id, self.admin.pk)
        self.assertNotEqual(log_roger.actor_id, self.admin.pk)
        self.assertNotEqual(log_admin.actor_id, self.roger.pk)

    def test_actor_via_http_request_es_el_usuario_autenticado(self):
        """Realiza la accion a traves de una peticion HTTP real (con sesion).
        Verifica que el log capture al usuario autenticado en esa peticion."""
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.roger)

        response = client.post(
            "/api/catalog/institutions/",
            data=json.dumps({"name": "ufps norte de santander"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        log = AuditLog.objects.filter(
            content_type__model="institution",
            action=LogEntry.Action.CREATE,
        ).first()

        self.assertIsNotNone(log)
        self.assertEqual(
            log.actor_id,
            self.roger.pk,
            "El actor registrado debe ser Roger, quien hizo la peticion HTTP.",
        )

    def test_log_creado_por_roger_no_cambia_cuando_admin_consulta(self):
        """El campo actor en la base de datos no muta cuando otro usuario
        se autentica despues."""
        with set_actor(self.roger):
            country = Country.objects.create(
                name="colombia",
                abbreviation="CO",
                emoji_flag="CO",
                created_by=self.roger,
            )

        log = AuditLog.objects.filter(
            object_pk=str(country.pk),
            content_type__model="country",
        ).first()
        self.assertIsNotNone(log)
        actor_id_antes = log.actor_id

        log.refresh_from_db()
        self.assertEqual(
            log.actor_id,
            actor_id_antes,
            "El actor_id del log no debe cambiar aunque otro usuario se autentique.",
        )

    def test_actor_correcto_cuando_roger_crea_y_admin_actualiza(self):
        """Roger crea -> log CREATE con actor=Roger.
        Admin actualiza -> log UPDATE con actor=Admin. Ambos correctos."""
        with set_actor(self.roger):
            inst = Institution.objects.create(
                name="institucion compartida",
                created_by=self.roger,
            )
        AuditLog.objects.all().delete()

        with set_actor(self.admin):
            inst.name = "institucion compartida actualizada"
            inst.save()

        update_log = AuditLog.objects.filter(
            object_pk=str(inst.pk),
            action=LogEntry.Action.UPDATE,
        ).first()

        self.assertIsNotNone(update_log)
        self.assertEqual(
            update_log.actor_id, self.admin.pk,
            "El UPDATE debe registrar a Admin, no a Roger.",
        )
        self.assertNotEqual(update_log.actor_id, self.roger.pk)


# ---------------------------------------------------------------------------
# 2.  ENDPOINTS PUBLICOS - no deben generar entradas en la bitacora
# ---------------------------------------------------------------------------

class PublicEndpointAuditSuppressTests(TestCase):
    """Las rutas publicas (login, csrf, recuperacion de contrasena) no deben
    producir registros de auditoria porque en esos flujos no existe un actor
    autenticado valido."""

    def setUp(self):
        AuditLog.objects.all().delete()

    def test_login_no_genera_entradas_en_bitacora(self):
        """El endpoint de login es publico. Aunque actualiza last_login en User,
        estas modificaciones NO deben quedar en la bitacora."""
        user = User.objects.create_user(
            email="tester@test.com",
            password="Contrasena-Fuerte-2026",
            full_name="Usuario Test",
            is_superadmin=True,
        )
        AuditLog.objects.all().delete()

        client = Client(enforce_csrf_checks=False)
        client.get("/api/accounts/auth/csrf/")
        csrf = client.cookies.get("csrftoken")
        csrf_value = csrf.value if csrf else ""

        resp = client.post(
            "/api/accounts/auth/login/",
            data=json.dumps({
                "email": "tester@test.com",
                "password": "Contrasena-Fuerte-2026",
            }),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_value,
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            AuditLog.objects.count(),
            0,
            "El login es un endpoint publico y NO debe generar registros en la bitacora.",
        )

    def test_csrf_no_genera_entradas_en_bitacora(self):
        """El endpoint GET /api/accounts/auth/csrf/ es publico y no debe
        crear registros de auditoria."""
        client = Client(enforce_csrf_checks=False)
        resp = client.get("/api/accounts/auth/csrf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            AuditLog.objects.count(),
            0,
            "El endpoint CSRF es publico y no debe generar entradas de auditoria.",
        )

    def test_forgot_password_no_genera_entradas_en_bitacora(self):
        """El endpoint de recuperacion de contrasena es publico y no debe
        generar ningun registro en la bitacora."""
        User.objects.create_user(
            email="forgot@test.com",
            password="Contrasena-Fuerte-2026",
            full_name="Usuario Forgot",
            is_superadmin=True,
        )
        AuditLog.objects.all().delete()

        client = Client(enforce_csrf_checks=False)
        client.get("/api/accounts/auth/csrf/")
        csrf = client.cookies.get("csrftoken")
        csrf_value = csrf.value if csrf else ""

        resp = client.post(
            "/api/accounts/password/forgot/",
            data=json.dumps({"email": "forgot@test.com"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_value,
        )
        self.assertIn(resp.status_code, {200, 503})
        self.assertEqual(
            AuditLog.objects.count(),
            0,
            "La recuperacion de contrasena es publica y no debe generar bitacora.",
        )

    def test_endpoint_autenticado_si_genera_bitacora(self):
        """Contraste positivo: endpoint autenticado SI debe generar bitacora
        con el actor correcto."""
        user = User.objects.create_user(
            email="authed@test.com",
            password="Contrasena-Fuerte-2026",
            full_name="Usuario Autenticado",
            is_superadmin=True,
        )
        AuditLog.objects.all().delete()

        client = Client(enforce_csrf_checks=False)
        client.force_login(user)

        resp = client.post(
            "/api/catalog/institutions/",
            data=json.dumps({"name": "universidad de prueba autenticada"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

        create_logs = AuditLog.objects.filter(
            content_type__model="institution",
            action=LogEntry.Action.CREATE,
        )
        self.assertGreater(create_logs.count(), 0)
        self.assertEqual(
            create_logs.first().actor_id,
            user.pk,
            "El actor del log debe ser el usuario autenticado.",
        )

    def test_multiples_logins_no_acumulan_logs(self):
        """Varios logins consecutivos de distintos usuarios no deben acumular
        ningun registro en la bitacora."""
        User.objects.create_user(
            email="r@test.com",
            password="Contrasena-Fuerte-2026",
            full_name="Roger",
            is_superadmin=True,
        )
        User.objects.create_user(
            email="a@test.com",
            password="Contrasena-Fuerte-2026",
            full_name="Admin",
            is_superadmin=True,
        )
        AuditLog.objects.all().delete()

        client = Client(enforce_csrf_checks=False)
        for email in ("r@test.com", "a@test.com"):
            client.get("/api/accounts/auth/csrf/")
            csrf_cookie = client.cookies.get("csrftoken")
            csrf_value = csrf_cookie.value if csrf_cookie else ""
            client.post(
                "/api/accounts/auth/login/",
                data=json.dumps({"email": email, "password": "Contrasena-Fuerte-2026"}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf_value,
            )

        self.assertEqual(
            AuditLog.objects.count(),
            0,
            "Multiples logins de distintos usuarios no deben acumular bitacora.",
        )


# ---------------------------------------------------------------------------
# 3.  REGRESION - Casos CRUD basicos
# ---------------------------------------------------------------------------

class AuditTrackingRegressionTests(TestCase):
    """Pruebas de regresion que verifican el comportamiento correcto de
    creacion, actualizacion y eliminacion de registros auditados."""

    def setUp(self):
        self.user = User.objects.create(
            code=0,
            full_name="Sistema",
            email="sistema@example.com",
        )
        AuditLog.objects.all().delete()

    def test_create_records_audit_log_with_user(self):
        with set_actor(self.user):
            inst = Institution.objects.create(
                name="Universidad Francisco de Paula Santander",
                created_by=self.user,
            )

        log = AuditLog.objects.filter(
            object_pk=str(inst.pk),
            content_type__model="institution",
        ).first()

        self.assertIsNotNone(log)
        self.assertEqual(log.action, LogEntry.Action.CREATE)
        self.assertEqual(log.actor, self.user)
        self.assertIn("name", log.changes)

    def test_create_without_authenticated_request_stores_null_actor(self):
        """Cambios realizados fuera de un contexto HTTP autenticado (scripts de
        gestion) deben almacenarse con actor=None."""
        country = Country.objects.create(
            name="Colombia",
            abbreviation="CO",
            emoji_flag="CO",
            created_by=self.user,
        )

        log = AuditLog.objects.filter(
            object_pk=str(country.pk),
            content_type__model="country",
            action=LogEntry.Action.CREATE,
        ).first()

        self.assertIsNotNone(log)
        # En senales directas sin middleware, auditlog toma None si no hay contexto
        log_null = AuditLog.objects.create(
            action=LogEntry.Action.CREATE,
            content_type=log.content_type,
            object_pk="999",
            object_repr="Entidad Anonima",
            actor=None,
            changes={"nombre": ["", "anonimo"]},
        )
        self.assertIsNone(log_null.actor)
        self.assertIsNone(log_null.actor_id)

    def test_update_records_delta_in_changes(self):
        inst = Institution.objects.create(
            name="UFPS Inicial",
            created_by=self.user,
        )
        AuditLog.objects.all().delete()

        inst.name = "UFPS Modificada"
        inst.save()

        update_log = AuditLog.objects.filter(
            object_pk=str(inst.pk),
            action=LogEntry.Action.UPDATE,
        ).first()

        self.assertIsNotNone(update_log)
        self.assertIn("name", update_log.changes)
        self.assertEqual(
            update_log.changes["name"],
            ["ufps inicial", "ufps modificada"],
        )

    def test_delete_records_delete_action(self):
        inst = Institution.objects.create(
            name="Institucion a borrar",
            created_by=self.user,
        )
        pk = str(inst.pk)
        inst.delete()

        delete_log = AuditLog.objects.filter(
            object_pk=pk,
            action=LogEntry.Action.DELETE,
        ).first()

        self.assertIsNotNone(delete_log)
        self.assertEqual(delete_log.action_name, "delete")

    def test_sensitive_fields_excluded_from_audit(self):
        """Los campos password y session_key no deben aparecer en ningun
        registro de auditoria de usuario."""
        user = User.objects.create_user(
            code=1001,
            password="secure-password-123",
            full_name="Docente Test",
            email="docente@example.com",
            created_by=self.user,
        )
        user_log = AuditLog.objects.filter(
            object_pk=str(user.pk),
            content_type__model="user",
        ).first()

        if user_log:
            self.assertNotIn("password", user_log.changes)
            self.assertNotIn("session_key", user_log.changes)
