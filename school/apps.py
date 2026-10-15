from django.apps import AppConfig


class SchoolConfig(AppConfig):
    name = 'school'

    def ready(self):
        from . import receivers  # noqa: F401  (connects the payment signal)
