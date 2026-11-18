from django.apps import AppConfig


class CameraConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "camera"

    def ready(self):
        from . import remember  # noqa: F401  (로그아웃 신호 연결)
