import base64
import os
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _get_fernet_instance():
    """
    Obtiene la instancia de Fernet usando una clave del .env
    (PLATFORM_ENCRYPTION_KEY) o derivándola de SECRET_KEY.
    """
    raw_key = os.getenv("PLATFORM_ENCRYPTION_KEY", getattr(settings, "SECRET_KEY", "default-insecure-key"))
    # Fernet requiere exactamente una clave de 32 bytes en formato base64 urlsafe
    key_bytes = raw_key.encode("utf-8")
    padded_key = key_bytes.ljust(32, b"0")[:32]
    fernet_key = base64.urlsafe_b64encode(padded_key)
    return Fernet(fernet_key)


def encrypt_api_key(raw_key: str | None) -> str:
    """Cifra una clave en texto plano."""
    if not raw_key:
        return ""
    cipher = _get_fernet_instance()
    return cipher.encrypt(raw_key.encode("utf-8")).decode("utf-8")


def decrypt_api_key(encrypted_key: str | None) -> str:
    """Descifra un texto cifrado y retorna la clave original."""
    if not encrypted_key:
        return ""
    cipher = _get_fernet_instance()
    try:
        return cipher.decrypt(encrypted_key.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""
