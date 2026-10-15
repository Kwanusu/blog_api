from django.apps import AppConfig


class BlogsConfig(AppConfig):
    name = 'blogs'

    def ready(self):
        from . import receivers  # noqa: F401  (connects the payment signal)
