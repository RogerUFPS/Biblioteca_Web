import os

from dotenv import load_dotenv

from .base import *

load_dotenv()

def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", os.getenv("SECRET_KEY"))
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in {"1", "true", "yes", "on"}
ROOT_URLCONF = "project.urls"
AUTH_USER_MODEL = "account.User"
WSGI_APPLICATION = "project.wsgi.application"
ASGI_APPLICATION = "project.asgi.application"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "localhost").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW", False)
CORS_ALLOW_CREDENTIALS = True
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev"),
)
RESEND_FROM_EMAIL = DEFAULT_FROM_EMAIL
CELERY_BROKER_URL = os.getenv(
    "CELERY_BROKER_URL",
    "amqp://harvest:harvest@rabbitmq:5672//",
)
CELERY_TASK_DEFAULT_QUEUE = "harvesting"
CELERY_TASK_ROUTES = {
    "apps.harvesting.process_harvest_step": {"queue": "harvesting"},
}
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
FRONTEND_LOGIN_URL = os.getenv(
    "FRONTEND_LOGIN_URL",
    "https://repositorio-biblioteca-frontend.vercel.app/admin/login",
)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 15 * 60
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "None" if not DEBUG else "Lax"
CSRF_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE

if os.getenv("DJANGO_TESTING", "").lower() in {"1", "true", "yes", "on"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "test.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", os.getenv("DATABASE_NAME")),
            "USER": os.getenv("POSTGRES_USER", os.getenv("DATABASE_USER")),
            "PASSWORD": os.getenv(
                "POSTGRES_PASSWORD",
                os.getenv("DATABASE_PASSWORD"),
            ),
            "HOST": os.getenv(
                "POSTGRES_HOST",
                os.getenv("DATABASE_HOST", "db"),
            ),
            "PORT": os.getenv(
                "POSTGRES_PORT",
                os.getenv("DATABASE_PORT", "5432"),
            ),
            "OPTIONS": {"sslmode": "require"},
        }
    }

SPECTACULAR_SETTINGS = {
    "TITLE": "API Sistema de Revistas",
    "DESCRIPTION": "Documentación de los endpoints del sistema.",
    "VERSION": "1.0.0",
}

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
