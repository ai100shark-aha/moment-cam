"""로그인 유지: 서버가 잠들었다 깨어나도 다시 로그인하지 않게 합니다.

무료 플랜은 서버가 재시작할 때마다 데이터베이스(로그인 기록 포함)가 지워집니다.
그래서 로그인할 때 '서명된 쿠키'를 휴대폰에 1년 동안 남겨 두고,
로그인 기록이 사라진 상태로 요청이 오면 이 쿠키를 확인해 자동으로 다시 로그인시킵니다.

쿠키에는 아이디만 들어 있고, SECRET_KEY로 서명되어 있어 위조할 수 없습니다.
(SECRET_KEY를 바꾸면 모든 휴대폰이 로그아웃됩니다.)
"""
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.signals import user_logged_out
from django.core import signing
from django.dispatch import receiver

COOKIE = "mc_remember"
SALT = "momentcam.remember"
MAX_AGE = 60 * 60 * 24 * 365


def _username_from(request):
    value = request.COOKIES.get(COOKIE)
    if not value:
        return None
    try:
        return signing.loads(value, salt=SALT, max_age=MAX_AGE).get("u")
    except (signing.BadSignature, AttributeError):
        return None


@receiver(user_logged_out)
def _forget(sender, request, **kwargs):
    if request is not None:
        request._mc_forget = True


class RememberMeMiddleware:
    """AuthenticationMiddleware 바로 뒤에 둡니다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            username = _username_from(request)
            if username:
                user = get_user_model().objects.filter(username=username, is_active=True).first()
                if user:
                    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

        response = self.get_response(request)

        if getattr(request, "_mc_forget", False):
            response.delete_cookie(COOKIE)
        elif request.user.is_authenticated and _username_from(request) != request.user.username:
            response.set_cookie(
                COOKIE,
                signing.dumps({"u": request.user.username}, salt=SALT),
                max_age=MAX_AGE,
                httponly=True,
                secure=not settings.DEBUG,
                samesite="Lax",
            )
        return response
