import hashlib

from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed


class CookieSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            return result
        cookie = request.COOKIES.get(self._session_cookie_name(request))
        if cookie:
            from .models import SessionTermination

            fingerprint = hashlib.sha256(cookie.encode("utf-8")).hexdigest()
            termination = SessionTermination.objects.filter(
                session_key_hash=fingerprint
            ).first()
            if termination:
                reason = termination.reason
                termination.delete()
                detail = (
                    "Esta sesión se cerró porque la cuenta inició sesión en otro lugar."
                    if reason == SessionTermination.Reason.LOGIN_REPLACED
                    else "Esta sesión se cerró porque cambiaron las credenciales o el estado de la cuenta."
                )
                raise AuthenticationFailed(
                    detail
                )
        return None

    @staticmethod
    def _session_cookie_name(request):
        from django.conf import settings

        return settings.SESSION_COOKIE_NAME

    def authenticate_header(self, request):
        return "Session"
