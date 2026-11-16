from django.conf import settings

from .services import caption, instagram


def app_info(request):
    return {
        "APP_NAME": settings.APP_NAME,
        "ig_ready": instagram.is_configured(),
        "ai_ready": caption.is_configured(),
    }
