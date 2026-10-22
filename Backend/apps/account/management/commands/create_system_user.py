from django.core.management.base import BaseCommand

from apps.account.models import User

SYSTEM_CODE = 0


class Command(BaseCommand):
    help = "Crea el usuario sistema como primer usuario del proyecto."

    def handle(self, *_args, **_options):
        if User.all_objects.filter(code=SYSTEM_CODE).exists():
            self.stdout.write("El usuario sistema ya existía.")
            return
        if User.all_objects.exists():
            self.stderr.write(
                self.style.ERROR(
                    "Ya existen usuarios. El usuario sistema debe ser el primero."
                )
            )
            return

        user = User(
            code=SYSTEM_CODE,
            full_name="Sistema",
            email="sistema@local.dev",
        )
        user.set_unusable_password()
        user.save()
        self.stdout.write(self.style.SUCCESS("Usuario sistema creado (code=0)."))
