from django.apps import AppConfig


class SchoolConfig(AppConfig):
    # Explicit so migrations never flip between AutoField and BigAutoField (review fix A5).
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'school'

    def ready(self):
        from . import receivers  # noqa: F401  (connects the payment signal)
