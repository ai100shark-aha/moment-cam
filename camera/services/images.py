"""사진 정리: 방향 보정, 크기 줄이기, 피드 비율 맞추기."""
import io

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_SIDE = 1920
# 인스타그램 피드가 받는 가로/세로 비율 범위 (4:5 ~ 1.91:1)
FEED_MIN_RATIO = 4 / 5
FEED_MAX_RATIO = 1.91


def _open(file_or_bytes):
    if isinstance(file_or_bytes, (bytes, bytearray)):
        file_or_bytes = io.BytesIO(file_or_bytes)
    img = Image.open(file_or_bytes)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def _to_jpeg(img, quality=88):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def normalize(uploaded_file):
    """업로드된 사진을 방향 보정한 JPEG(긴 변 1920px 이하)으로 바꿉니다."""
    img = _open(uploaded_file)
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    return ContentFile(_to_jpeg(img), name="photo.jpg")


def small_jpeg(image_bytes, side=1024):
    """AI에 보낼 작은 사본 (비용 절약)."""
    img = _open(image_bytes)
    img.thumbnail((side, side))
    return _to_jpeg(img, quality=80)


def feed_safe(image_bytes):
    """피드에 올릴 수 없는 비율(예: 세로로 긴 스토리 사진)이면 가운데를 잘라 맞춥니다.

    바꿀 필요가 없으면 None을 돌려줍니다.
    """
    img = _open(image_bytes)
    w, h = img.size
    ratio = w / h
    if FEED_MIN_RATIO <= ratio <= FEED_MAX_RATIO:
        return None
    if ratio < FEED_MIN_RATIO:  # 너무 세로로 김 → 위아래를 자름
        new_h = round(w / FEED_MIN_RATIO)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    else:  # 너무 가로로 김 → 좌우를 자름
        new_w = round(h * FEED_MAX_RATIO)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    return _to_jpeg(img)
