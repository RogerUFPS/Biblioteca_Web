import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0002_remove_user_is_staff_remove_user_is_superuser"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="code",
            field=models.IntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="user",
            name="full_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(max_length=254, unique=True),
        ),
        migrations.AddField(
            model_name="user",
            name="collegue_code",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="user",
            name="force_password_change",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="is_superadmin",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="permissions",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="user",
            name="session_key",
            field=models.CharField(blank=True, max_length=40, null=True),
        ),
        migrations.CreateModel(
            name="AccessPreset",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120, unique=True)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("permissions", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="access_presets_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="access_presets_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="user",
            name="presets",
            field=models.ManyToManyField(
                blank=True,
                related_name="users",
                to="account.accesspreset",
            ),
        ),
        migrations.CreateModel(
            name="SessionTermination",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("session_key_hash", models.CharField(max_length=64, unique=True)),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("login_replaced", "Sesión reemplazada"),
                            ("credentials_reset", "Credenciales restablecidas"),
                            ("account_disabled", "Cuenta desactivada"),
                        ],
                        default="login_replaced",
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
