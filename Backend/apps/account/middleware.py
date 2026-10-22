from auditlog.context import disable_auditlog

from .permissions import PUBLIC_ACCOUNT_PATHS


class AuditDisableForPublicMiddleware:
    """
    Deshabilita el registro de auditoría (django-auditlog) para los
    endpoints públicos que no requieren autenticación.

    Esto evita que operaciones como login, registro y recuperación de
    contraseña generen entradas en la bitácora, ya que en esos flujos
    el usuario aún no está autenticado y no existe un «actor» válido.

    Las rutas cubiertas son las declaradas en PUBLIC_ACCOUNT_PATHS
    del módulo de permisos:
        - /api/accounts/auth/csrf/
        - /api/accounts/auth/login/
        - /api/accounts/register/
        - /api/accounts/password/forgot/
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info.rstrip("/") + "/"
        if path in PUBLIC_ACCOUNT_PATHS:
            with disable_auditlog():
                return self.get_response(request)
        return self.get_response(request)
