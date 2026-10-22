import secrets
from html import escape

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.sessions.backends.db import SessionStore
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .email import EmailDeliveryError, login_link_html, send_email
from .models import AccessPreset, SessionTermination, User
from .permissions import PERMISSION_MATRIX
from .serializers import (
    AccessPresetSerializer,
    AssignPresetsSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    InviteSerializer,
    LoginSerializer,
    ProfileSerializer,
    RegistrationSerializer,
    UserAdminUpdateSerializer,
    UserPermissionsSerializer,
    UserSerializer,
)


def temporary_password():
    return secrets.token_urlsafe(18)


def invalidate_current_session(user, reason):
    session_key = user.session_key
    if session_key:
        SessionTermination.record(user, session_key, reason=reason)
        SessionStore(session_key=session_key).delete()
        user.session_key = None


class CsrfView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({"detail": "Token CSRF disponible en la cookie csrftoken."})


class LoginView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        user = authenticate(
            request,
            email=email,
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {"detail": "Correo o contraseña incorrectos."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            previous_session_terminated = bool(
                user.session_key and user.session_key != request.session.session_key
            )
            if previous_session_terminated:
                SessionTermination.record(user, user.session_key)
                SessionStore(session_key=user.session_key).delete()
            login(request, user)
            request.session.save()
            user.session_key = request.session.session_key
            user.save(update_fields=["session_key"])

        return Response({
            "user": UserSerializer(user).data,
            "must_change_password": user.force_password_change,
            "previous_session_terminated": previous_session_terminated,
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.session_key == request.session.session_key:
            request.user.session_key = None
            request.user.save(update_fields=["session_key"])
        logout(request)
        return Response({"detail": "Sesión cerrada."})


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.create_user(**serializer.validated_data)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        if request.user.force_password_change:
            return Response(
                {"detail": "Debes cambiar tu contraseña antes de continuar."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user, updated_at=timezone.now())
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        if not request.user.check_password(serializer.validated_data["current_password"]):
            return Response(
                {"current_password": ["La contraseña actual no es correcta."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.force_password_change = False
        request.user.updated_by = request.user
        request.user.updated_at = timezone.now()
        request.user.save()
        update_session_auth_hash(request, request.user)
        request.user.session_key = request.session.session_key
        request.user.save(update_fields=["session_key"])
        return Response({"detail": "La contraseña se cambió correctamente."})


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(csrf_protect)
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(
            email__iexact=serializer.validated_data["email"].strip(),
            is_active=True,
        ).first()
        if user is None:
            return Response({
                "detail": "Si el correo está registrado, recibirás una contraseña provisional."
            })

        password = temporary_password()
        try:
            send_email(
                user.email,
                "Recuperación de contraseña",
                (
                    "<p>Tu contraseña provisional es:</p>"
                    f"<p><strong>{escape(password)}</strong></p>"
                    "<p>Inicia sesión y cámbiala antes de continuar.</p>"
                    f"{login_link_html()}"
                ),
            )
        except EmailDeliveryError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        invalidate_current_session(
            user,
            reason=SessionTermination.Reason.CREDENTIALS_RESET,
        )
        user.set_password(password)
        user.force_password_change = True
        user.save(update_fields=["password", "force_password_change", "session_key"])
        return Response({
            "detail": "Si el correo está registrado, recibirás una contraseña provisional."
        })


class UsersView(APIView):
    def get(self, request):
        return Response(UserSerializer(User.objects.order_by("id"), many=True).data)


class ArchivedUsersView(APIView):
    def get(self, request):
        users = User.all_objects.filter(
            deleted_at__isnull=False,
        ).order_by("id")
        return Response(UserSerializer(users, many=True).data)


class UserDetailView(APIView):
    def get_object(self, pk):
        return User.all_objects.filter(pk=pk, deleted_at__isnull=True).first()

    def get(self, request, pk):
        user = self.get_object(pk)
        if user is None:
            return Response({"detail": "Cuenta no encontrada."}, status=404)
        return Response(UserSerializer(user).data)

    def patch(self, request, pk):
        user = self.get_object(pk)
        if user is None:
            return Response({"detail": "Cuenta no encontrada."}, status=404)
        if user.is_superadmin:
            return Response(
                {"detail": "No se puede modificar la cuenta superadmin desde este endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = UserAdminUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("is_active") is False:
            invalidate_current_session(
                user,
                reason=SessionTermination.Reason.ACCOUNT_DISABLED,
            )
        serializer.save(updated_by=request.user, updated_at=timezone.now())
        return Response(UserSerializer(user).data)

    def delete(self, request, pk):
        user = self.get_object(pk)
        if user is None or user.deleted_at is not None:
            return Response({"detail": "Cuenta no encontrada."}, status=404)
        if user.is_superadmin:
            return Response(
                {"detail": "No se puede desactivar la cuenta superadmin."},
                status=status.HTTP_403_FORBIDDEN,
            )
        invalidate_current_session(
            user,
            reason=SessionTermination.Reason.ACCOUNT_DISABLED,
        )
        user.is_active = False
        user.soft_delete(user=request.user, explanation="Cuenta desactivada por administración")
        user.save(update_fields=["is_active", "session_key"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserRestoreView(APIView):
    @transaction.atomic
    def post(self, request, pk):
        user = User.all_objects.select_for_update().filter(pk=pk).first()
        if user is None:
            return Response({"detail": "Cuenta no encontrada."}, status=404)
        if user.is_superadmin:
            return Response(
                {"detail": "No se puede restaurar la cuenta superadmin desde este endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if user.deleted_at is None and user.is_active:
            return Response(
                {"detail": "La cuenta ya está activa."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.restore()
        user.is_active = True
        user.updated_by = request.user
        user.updated_at = timezone.now()
        user.session_key = None
        user.save(update_fields=[
            "is_active",
            "deleted_by",
            "deleted_at",
            "delete_explanation",
            "updated_by",
            "updated_at",
            "session_key",
        ])
        return Response(UserSerializer(user).data)


class InviteView(APIView):
    def post(self, request):
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        password = temporary_password()
        values = serializer.validated_data
        with transaction.atomic():
            user = User.objects.create_user(
                email=values["email"],
                password=password,
                full_name=values.get("full_name", ""),
                collegue_code=values.get("collegue_code", ""),
                force_password_change=True,
                created_by=request.user,
            )
            try:
                send_email(
                    user.email,
                    "Invitación al sistema de revistas",
                    (
                        f"<p>Tu correo de acceso es: {escape(user.email)}</p>"
                        "<p>Tu contraseña provisional es:</p>"
                        f"<p><strong>{escape(password)}</strong></p>"
                        "<p>Inicia sesión y cámbiala antes de continuar.</p>"
                        f"{login_link_html()}"
                    ),
                )
            except EmailDeliveryError as error:
                transaction.set_rollback(True)
                return Response(
                    {"detail": str(error)},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserPermissionsView(APIView):
    def put(self, request, pk):
        user = User.all_objects.filter(pk=pk).first()
        if user is None or user.deleted_at is not None:
            return Response({"detail": "Cuenta no encontrada."}, status=404)
        if user.is_superadmin:
            return Response(
                {"detail": "Los permisos del superadmin no se pueden modificar."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = UserPermissionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user.permissions = serializer.validated_data["permissions"]
        user.updated_by = request.user
        user.updated_at = timezone.now()
        user.save(update_fields=["permissions", "updated_by", "updated_at"])
        return Response(UserSerializer(user).data)


class UserPresetsView(APIView):
    def put(self, request, pk):
        user = User.all_objects.filter(pk=pk).first()
        if user is None or user.deleted_at is not None:
            return Response({"detail": "Cuenta no encontrada."}, status=404)
        if user.is_superadmin:
            return Response(
                {"detail": "No se pueden asignar presets al superadmin."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = AssignPresetsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user.presets.set(serializer.validated_data["preset_ids"])
        user.updated_by = request.user
        user.updated_at = timezone.now()
        user.save(update_fields=["updated_by", "updated_at"])
        return Response(UserSerializer(user).data)


class PresetsView(APIView):
    def get(self, request):
        return Response(AccessPresetSerializer(AccessPreset.objects.all(), many=True).data)

    def post(self, request):
        serializer = AccessPresetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PresetDetailView(APIView):
    def get_object(self, pk):
        return AccessPreset.objects.filter(pk=pk).first()

    def get(self, request, pk):
        preset = self.get_object(pk)
        if preset is None:
            return Response({"detail": "Preset no encontrado."}, status=404)
        return Response(AccessPresetSerializer(preset).data)

    def patch(self, request, pk):
        preset = self.get_object(pk)
        if preset is None:
            return Response({"detail": "Preset no encontrado."}, status=404)
        serializer = AccessPresetSerializer(preset, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user, updated_at=timezone.now())
        return Response(serializer.data)

    def delete(self, request, pk):
        preset = self.get_object(pk)
        if preset is None:
            return Response({"detail": "Preset no encontrado."}, status=404)
        preset.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PermissionsView(APIView):
    def get(self, request):
        return Response({
            app: {
                resource: list(actions)
                for resource, actions in resources.items()
            }
            for app, resources in PERMISSION_MATRIX.items()
        })
