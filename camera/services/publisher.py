"""사진을 실제로 게시하고 결과를 기록합니다."""
import logging
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from ..models import AppSettings, Photo
from . import images, instagram

log = logging.getLogger("camera")


def absolute_url(request, path):
    base = settings.PUBLIC_BASE_URL or request.build_absolute_uri("/").rstrip("/")
    return base + path


def _feed_url(request, photo):
    """피드 비율에 맞는 사진 주소. 필요하면 잘라낸 사본을 만들어 씁니다."""
    with photo.image.open("rb") as fh:
        cropped = images.feed_safe(fh.read())
    if cropped is None:
        return absolute_url(request, photo.image.url)
    name = default_storage.save(f"feed/{uuid.uuid4().hex}.jpg", ContentFile(cropped))
    return absolute_url(request, default_storage.url(name))


def feed_caption(photo):
    parts = [photo.caption.strip(), photo.race_line, photo.hashtags.strip()]
    return "\n".join(p for p in parts if p)


def _mark_posted(photos, media_id):
    now = timezone.now()
    for photo in photos:
        photo.status = Photo.POSTED
        photo.ig_media_id = media_id
        photo.posted_at = now
        photo.error = ""
        photo.save()


def _mark_failed(photos, exc):
    log.warning("게시 실패: %s", exc)
    for photo in photos:
        photo.status = Photo.FAILED
        photo.error = str(exc)
        photo.save()


def publish(request, photo):
    """사진 한 장을 설정된 위치(스토리/피드)에 올립니다. 성공 여부를 돌려줍니다."""
    if photo.status == Photo.POSTED:
        return True
    try:
        if photo.target == AppSettings.TARGET_STORY:
            url = absolute_url(request, photo.image.url)
            media_id = instagram.publish_photo(url, story=True)
        else:
            media_id = instagram.publish_photo(
                _feed_url(request, photo), feed_caption(photo)
            )
    except instagram.InstagramError as exc:
        _mark_failed([photo], exc)
        return False
    _mark_posted([photo], media_id)
    return True


def publish_bundle(request, photos, caption):
    """여러 장을 한 게시물로 묶어 피드에 올립니다."""
    photos = list(photos)[: instagram.MAX_CAROUSEL]
    try:
        urls = [_feed_url(request, p) for p in photos]
        media_id = instagram.publish_carousel(urls, caption)
    except instagram.InstagramError as exc:
        _mark_failed(photos, exc)
        return False
    for photo in photos:
        photo.target = AppSettings.TARGET_FEED
    _mark_posted(photos, media_id)
    return True
