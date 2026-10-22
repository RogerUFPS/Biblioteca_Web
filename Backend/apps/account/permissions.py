from rest_framework.permissions import BasePermission


CRUD = ("view", "create", "update", "delete", "restore")

PERMISSION_MATRIX = {
    "audit": {"logs": {"view": True}},
    "catalog": {
        resource: {action: True for action in CRUD}
        for resource in (
            "institutions",
            "languages",
            "countries",
            "material-types",
            "editorials",
            "knowledge-areas",
            "academic-programs",
        )
    },
    "journals": {
        "journals": {
            action: True
            for action in (
                "view",
                "create",
                "update",
                "delete",
                "publish",
                "deactivate",
                "restore",
            )
        }
    },
    "platforms": {
        "platforms": {
            action: True
            for action in (
                "view",
                "create",
                "update",
                "delete",
                "publish",
                "mark_obsolete",
                "reactivate",
                "check_link",
                "restore",
            )
        },
        "valid-sintaxis": {action: True for action in CRUD},
        "link-check-logs": {"view": True},
    },
    "harvesting": {
        "schedules": {
            action: True
            for action in (*CRUD, "run_due")
        },
        "events": {"view": True},
        "harvests": {"view": True, "pause": True, "resume": True},
    },
    "accounts": {
        "users": {
            action: True
            for action in (
                "view",
                "update",
                "delete",
                "restore",
                "invite",
                "manage_permissions",
            )
        },
        "presets": {action: True for action in ("view", "create", "update", "delete")},
        "permissions": {"view": True},
    },
}

APP_PREFIXES = {
    "catalog": "catalog",
    "journals": "journals",
    "platforms": "platforms",
    "harvesting": "harvesting",
    "audit": "audit",
    "accounts": "accounts",
}

PUBLIC_ACCOUNT_PATHS = {
    "/api/accounts/auth/csrf/",
    "/api/accounts/auth/login/",
    "/api/accounts/register/",
    "/api/accounts/password/forgot/",
}
SELF_ACCOUNT_PATHS = {
    "/api/accounts/auth/logout/",
    "/api/accounts/password/change/",
}

ACTION_NAMES = {
    "invite": "invite",
    "publish": "publish",
    "deactivate": "deactivate",
    "restore": "restore",
    "reactivate": "reactivate",
    "mark-obsolete": "mark_obsolete",
    "check-link": "check_link",
    "run-due": "run_due",
    "pause": "pause",
    "resume": "resume",
}


def normalize_permissions(value):
    if not isinstance(value, dict):
        raise ValueError("Los permisos deben ser un objeto JSON.")
    normalized = {}
    for app, resources in value.items():
        if app not in PERMISSION_MATRIX or not isinstance(resources, dict):
            raise ValueError(f"Sección de permisos no válida: {app}.")
        for resource, actions in resources.items():
            allowed_actions = PERMISSION_MATRIX[app].get(resource)
            if allowed_actions is None or not isinstance(actions, dict):
                raise ValueError(f"Recurso de permisos no válido: {app}.{resource}.")
            if set(actions) - set(allowed_actions):
                invalid = ", ".join(sorted(set(actions) - set(allowed_actions)))
                raise ValueError(f"Acciones no válidas para {app}.{resource}: {invalid}.")
            if any(not isinstance(enabled, bool) for enabled in actions.values()):
                raise ValueError("Cada permiso debe ser true o false.")
            target = normalized.setdefault(app, {}).setdefault(resource, {})
            target.update(actions)
            if any(enabled for action, enabled in actions.items() if action != "view"):
                target["view"] = True
    return normalized


def has_permission(user, app, resource, action):
    if user.is_superadmin:
        return True
    return bool(
        user.effective_permissions()
        .get(app, {})
        .get(resource, {})
        .get(action, False)
    )


class ApplicationPermission(BasePermission):
    message = "No tienes permiso para realizar esta acción."

    def has_permission(self, request, view):
        path = request.path_info.rstrip("/") + "/"
        if path in PUBLIC_ACCOUNT_PATHS:
            return True
        if (
            path == "/api/harvesting/schedules/run-due/"
            and request.method == "POST"
        ):
            return True
        if path == "/api/accounts/auth/me/":
            return bool(
                request.user
                and request.user.is_authenticated
                and (
                    request.method == "GET"
                    or not request.user.force_password_change
                )
            )
        if path == "/api/accounts/permissions/":
            return bool(
                request.user
                and request.user.is_authenticated
                and not request.user.force_password_change
            )
        if path in SELF_ACCOUNT_PATHS:
            return bool(request.user and request.user.is_authenticated)

        segments = [part for part in path.strip("/").split("/") if part]
        if len(segments) < 2 or segments[0] != "api":
            return True
        app = segments[1]
        if app not in APP_PREFIXES:
            return True
        tail = segments[2:]

        if app == "catalog" and request.method == "GET":
            return True
        if app in {"journals", "platforms"} and tail and tail[0] == "public":
            return request.method == "GET"

        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.force_password_change:
            self.message = "Debes cambiar tu contraseña antes de continuar."
            return False

        resource = self._resource(app, tail)
        if resource is None:
            return False
        operation = self._operation(request.method, tail)
        if (
            app == "accounts"
            and tail
            and tail[0] == "users"
            and len(tail) > 2
            and tail[-1] in {"permissions", "presets"}
        ):
            operation = "manage_permissions"
        return has_permission(request.user, app, resource, operation)

    @staticmethod
    def _resource(app, tail):
        if app in {"journals", "audit"}:
            return "journals" if app == "journals" else (tail[0] if tail else "logs")
        if app == "platforms":
            return tail[0] if tail and tail[0] in {
                "valid-sintaxis",
                "link-check-logs",
            } else "platforms"
        if app in {"catalog", "harvesting", "accounts"}:
            if not tail:
                return None
            if app == "catalog":
                return tail[0]
            return tail[0]
        return None

    @staticmethod
    def _operation(method, tail):
        action_name = next(
            (ACTION_NAMES[part] for part in reversed(tail) if part in ACTION_NAMES),
            None,
        )
        if action_name:
            return action_name
        return {
            "GET": "view",
            "HEAD": "view",
            "OPTIONS": "view",
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }.get(method, "view")
