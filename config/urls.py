from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path
from django.http import Http404, HttpResponse
from django.utils._os import safe_join


def media_file(request, path):
    """사진 파일을 그대로 돌려줍니다.

    인스타그램 서버가 이 주소에서 사진을 가져가므로, 파일 내용을 한 번에 담아
    정확한 크기(Content-Length)와 형식(image/jpeg)으로 보냅니다.
    """
    try:
        full = safe_join(str(settings.MEDIA_ROOT), path)
        with open(full, "rb") as fh:
            data = fh.read()
    except (OSError, ValueError, Exception):
        raise Http404("사진이 없어요.")
    content_type = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "application/octet-stream"
    response = HttpResponse(data, content_type=content_type)
    response["Cache-Control"] = "public, max-age=86400"
    return response

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="camera/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # 인스타그램이 사진을 가져가야 하므로 사진 파일은 공개 주소로 제공합니다.
    # 파일 이름은 추측할 수 없는 무작위 값입니다.
    re_path(r"^media/(?P<path>.*)$", media_file),
    path("", include("camera.urls")),
]
