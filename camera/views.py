import datetime
import json
import uuid
from functools import wraps

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from .models import AppSettings, Photo, RaceSession
from .services import blog, caption, images, instagram, publisher


# ---- 공통 ----------------------------------------------------------------
def api_login_required(view):
    """API는 로그인 화면으로 보내는 대신 401을 돌려줍니다 (오프라인 대기열이 알 수 있게)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "로그인이 필요해요."}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def _json(request):
    try:
        return json.loads(request.body or "{}")
    except ValueError:
        return {}


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _race_dict(race):
    if not race:
        return None
    return {"id": race.pk, "name": race.name, "started_at": race.started_at.isoformat()}


# ---- 화면 ----------------------------------------------------------------
@login_required
def camera_view(request):
    state = {
        "settings": AppSettings.load().as_dict(),
        "race": _race_dict(RaceSession.active()),
    }
    return render(request, "camera/camera.html", {"state": state})


class SettingsForm(forms.ModelForm):
    class Meta:
        model = AppSettings
        fields = [
            "post_instagram",
            "make_blog_draft",
            "daily_target",
            "daily_batch",
            "cancel_seconds",
            "group_check",
            "offline_queue",
            "ai_caption",
        ]

    def clean_cancel_seconds(self):
        return min(self.cleaned_data["cancel_seconds"], 10)


@login_required
def settings_view(request):
    obj = AppSettings.load()
    if request.method == "POST":
        form = SettingsForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "설정을 저장했어요.")
            return redirect("settings")
    return render(request, "camera/settings.html", {"s": obj})


@login_required
def today_view(request):
    try:
        day = datetime.date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = timezone.localdate()
    photos = list(blog.photos_for(day).select_related("race"))
    waiting = [p for p in photos if p.status != Photo.POSTED]
    context = {
        "day": day,
        "prev_day": day - datetime.timedelta(days=1),
        "next_day": day + datetime.timedelta(days=1),
        "is_today": day == timezone.localdate(),
        "photos": photos,
        "waiting_count": len(waiting),
        "draft": blog.build(day, photos),
        "s": AppSettings.load(),
    }
    return render(request, "camera/today.html", context)


# ---- PWA 파일 ------------------------------------------------------------
@require_GET
def manifest(request):
    data = {
        "name": settings.APP_NAME,
        "short_name": settings.APP_NAME,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0E0F11",
        "theme_color": "#0E0F11",
        "lang": "ko",
        "icons": [
            {"src": static("camera/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("camera/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {
                "src": static("camera/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


@require_GET
def service_worker(request):
    response = render(
        request,
        "camera/sw.js",
        {
            "assets": [
                static("camera/app.css"),
                static("camera/camera.js"),
                static("camera/icon-192.png"),
            ]
        },
        content_type="application/javascript",
    )
    response["Cache-Control"] = "no-cache"
    return response


# ---- API -----------------------------------------------------------------
@api_login_required
@require_GET
def api_state(request):
    return JsonResponse(
        {
            "settings": AppSettings.load().as_dict(),
            "race": _race_dict(RaceSession.active()),
        }
    )


@api_login_required
@require_POST
def api_upload(request):
    """사진을 받아 저장하고, AI 캡션과 인원수를 붙여 돌려줍니다."""
    upload = request.FILES.get("image")
    if not upload:
        return JsonResponse({"error": "사진이 없어요."}, status=400)

    # 신호가 불안정할 때 같은 사진이 두 번 올라와도 한 번만 저장합니다.
    try:
        client_id = uuid.UUID(request.POST.get("client_id", ""))
    except ValueError:
        client_id = uuid.uuid4()
    existing = Photo.objects.filter(client_id=client_id).first()
    if existing:
        return JsonResponse(_upload_response(existing, duplicate=True))

    s = AppSettings.load()
    mode = Photo.MODE_RACE if request.POST.get("mode") == "race" else Photo.MODE_DAILY
    race = RaceSession.active() if mode == Photo.MODE_RACE else None

    try:
        image_file = images.normalize(upload)
    except Exception:
        return JsonResponse({"error": "사진 파일을 읽지 못했어요."}, status=400)

    photo = Photo(
        client_id=client_id,
        mode=mode,
        race=race,
        taken_at=parse_datetime(request.POST.get("taken_at", "")) or timezone.now(),
        distance_km=_float(request.POST.get("distance_km")),
        section=request.POST.get("section", "")[:60],
        lat=_float(request.POST.get("lat")),
        lng=_float(request.POST.get("lng")),
        target=(
            AppSettings.TARGET_STORY if mode == Photo.MODE_RACE else s.daily_target
        ),
    )
    elapsed = _float(request.POST.get("elapsed_seconds"))
    photo.elapsed_seconds = int(elapsed) if elapsed is not None and elapsed >= 0 else None
    photo.image.save("photo.jpg", image_file, save=False)

    people = None
    if s.ai_caption or s.group_check:
        with photo.image.open("rb") as fh:
            result = caption.analyze(
                fh.read(), mode, race.name if race else "", taken_at=photo.taken_at
            )
        if s.ai_caption:
            photo.caption = result["caption"]
            photo.hashtags = result["hashtags"]
        people = result["people_count"]
    # 휴대폰이 직접 센 얼굴 수가 있으면 더 큰 쪽을 믿습니다 (놓치는 것보다 한 번 더 묻는 편이 안전).
    client_faces = _float(request.POST.get("client_faces"))
    if client_faces is not None:
        people = max(people or 0, int(client_faces))
    photo.people_count = people

    if s.group_check and (people or 0) >= 2:
        photo.status = Photo.NEEDS_CONSENT
    elif not s.post_instagram or (mode == Photo.MODE_DAILY and s.daily_batch):
        photo.status = Photo.QUEUED
    else:
        photo.status = Photo.DRAFT
    photo.save()
    return JsonResponse(_upload_response(photo))


def _upload_response(photo, duplicate=False):
    data = photo.as_dict()
    data.update(
        {
            "duplicate": duplicate,
            "race_line": photo.race_line,
            "cancel_seconds": AppSettings.load().cancel_seconds,
        }
    )
    return data


@api_login_required
@require_POST
def api_publish(request, pk):
    photo = get_object_or_404(Photo, pk=pk)
    data = _json(request)
    if photo.status != Photo.POSTED:
        if "caption" in data:
            photo.caption = str(data["caption"])[:2000]
        if "hashtags" in data:
            photo.hashtags = str(data["hashtags"])[:300]
        photo.save()
    ok = publisher.publish(request, photo)
    return JsonResponse(photo.as_dict(), status=200 if ok else 502)


@api_login_required
@require_POST
def api_cancel(request, pk):
    photo = get_object_or_404(Photo, pk=pk)
    if photo.status == Photo.POSTED:
        return JsonResponse({"error": "이미 게시된 사진이에요."}, status=409)
    photo.status = Photo.CANCELLED
    photo.save()
    return JsonResponse(photo.as_dict())


@api_login_required
@require_POST
def api_bundle(request):
    """고른 사진들을 한 게시물로 묶어 피드에 올립니다 (완주 후 베스트 사진, 모아서 올리기)."""
    data = _json(request)
    ids = [int(i) for i in data.get("ids", []) if str(i).isdigit()]
    photos = list(Photo.objects.filter(pk__in=ids).exclude(status=Photo.CANCELLED))
    if not photos:
        return JsonResponse({"error": "올릴 사진을 골라 주세요."}, status=400)
    if len(photos) > 10:
        return JsonResponse({"error": "한 번에 10장까지 묶을 수 있어요."}, status=400)
    ok = publisher.publish_bundle(request, photos, str(data.get("caption", ""))[:2000])
    if not ok:
        return JsonResponse({"error": photos[0].error or "게시하지 못했어요."}, status=502)
    return JsonResponse({"ok": True, "count": len(photos)})


@api_login_required
@require_POST
def api_race_start(request):
    name = str(_json(request).get("name", "")).strip()[:100] or "레이스"
    RaceSession.objects.filter(finished_at__isnull=True).update(
        finished_at=timezone.now()
    )
    race = RaceSession.objects.create(name=name)
    return JsonResponse({"race": _race_dict(race)})


@api_login_required
@require_POST
def api_race_finish(request):
    race = RaceSession.active()
    if race:
        race.finished_at = timezone.now()
        race.save()
    return JsonResponse({"race": None, "finished": _race_dict(race)})


def offline(request):
    return HttpResponse(
        "<!doctype html><meta charset=utf-8><title>오프라인</title>"
        "<body style='background:#0E0F11;color:#F4F2EE;font-family:sans-serif;padding:32px'>"
        "<h1>신호가 없어요</h1><p>신호가 잡히면 다시 열어 주세요.</p>"
    )


@api_login_required
@require_POST
def api_diagnose(request):
    """설정 화면의 '연결 점검': Claude 키와 인스타그램 토큰이 실제로 동작하는지 시험합니다."""
    ai_ok, ai_text = caption.check()
    ig_ok, ig_text = instagram.check()
    base = settings.PUBLIC_BASE_URL
    return JsonResponse(
        {
            "checks": [
                {"name": "AI 캡션 (Claude)", "ok": ai_ok, "detail": ai_text},
                {"name": "인스타그램", "ok": ig_ok, "detail": ig_text},
                {
                    "name": "앱 주소",
                    "ok": base.startswith("https://"),
                    "detail": base or "PUBLIC_BASE_URL 값이 비어 있어요.",
                },
            ]
        }
    )
