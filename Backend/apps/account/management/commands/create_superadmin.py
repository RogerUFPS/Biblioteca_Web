from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.account.models import User


class Command(BaseCommand):
    help = "Crea un superadmin solicitando la contraseña de forma interactiva."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--full-name", required=True)
        parser.add_argument("--collegue-code", default="")

    def handle(self, *_args, **options):
        email = options["email"].strip().lower()
        if User.all_objects.filter(is_superadmin=True).exists():
            raise CommandError("Ya existe una cuenta superadmin.")
        if User.all_objects.filter(email__iexact=email).exists():
            raise CommandError("Ya existe una cuenta con ese correo.")
        password = getpass("Contraseña (mínimo 12 caracteres): ")
        confirmation = getpass("Confirma la contraseña: ")
        if password != confirmation:
            raise CommandError("Las contraseñas no coinciden.")
        try:
            validate_password(password)
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error

        first_user = User.all_objects.order_by("pk").first()
        user = User.objects.create_superuser(
            email=email,
            password=password,
            full_name=options["full_name"],
            collegue_code=options["collegue_code"],
            code=0 if not User.all_objects.filter(code=0).exists() else None,
            created_by=first_user,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Superadmin creado con el identificador {user.pk}."
        ))
