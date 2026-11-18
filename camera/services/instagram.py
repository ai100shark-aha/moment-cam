"""Instagram Graph API로 사진을 올립니다 (크리에이터/비즈니스 계정 전용).

흐름: ① 사진 주소로 '컨테이너'를 만들고 → ② 그 컨테이너를 '게시'합니다.
IG_USER_ID / IG_ACCESS_TOKEN 이 없으면 '연습 모드'로 동작해
실제로 올리지 않고 올린 것처럼 기록만 남깁니다.
"""
import logging
import time
import uuid

import requests
from django.conf import settings

log = logging.getLogger("camera")

TIMEOUT = 30
API_VERSION = "v25.0"
# 인스타그램이 사진 주소를 읽지 못했을 때 내는 오류 번호 (잠시 뒤 다시 시도하면 되는 경우가 많음)
RETRY_CODES = {9004, 2207052, 2207003}
MAX_CAROUSEL = 10


class InstagramError(Exception):
    pass


def is_configured():
    return bool(settings.IG_USER_ID and settings.IG_ACCESS_TOKEN)


def _token():
    return settings.IG_ACCESS_TOKEN.strip()


def graph_url():
    """토큰 종류에 맞는 주소를 고릅니다.

    Instagram 로그인으로 받은 토큰(IGAA…)은 graph.instagram.com,
    Facebook/비즈니스 로그인으로 받은 토큰(EAA…)은 graph.facebook.com 을 씁니다.
    IG_GRAPH_URL 을 직접 넣었으면 그 값을 따릅니다.
    """
    if settings.IG_GRAPH_URL_SET:
        return settings.IG_GRAPH_URL.rstrip("/")
    host = "graph.instagram.com" if _token().startswith("IG") else "graph.facebook.com"
    return f"https://{host}/{API_VERSION}"


def _call(method, path, **params):
    params["access_token"] = _token()
    url = f"{graph_url()}/{path}"
    try:
        if method == "GET":
            resp = requests.get(url, params=params, timeout=TIMEOUT)
        else:
            resp = requests.post(url, data=params, timeout=TIMEOUT)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise InstagramError(f"인스타그램에 연결하지 못했어요: {exc}") from exc
    if "error" in data:
        err = data["error"]
        log.warning("인스타그램 오류 %s: %s", path, err)
        exc = InstagramError(err.get("error_user_msg") or err.get("message") or str(err))
        exc.codes = {err.get("code"), err.get("error_subcode")}
        raise exc
    return data


def _create_container(**params):
    """컨테이너를 만듭니다. 인스타그램이 사진을 못 읽었다고 하면 잠시 뒤 두 번까지 다시 시도합니다."""
    for attempt in range(3):
        try:
            return _call("POST", f"{settings.IG_USER_ID}/media", **params)["id"]
        except InstagramError as exc:
            if attempt == 2 or not (getattr(exc, "codes", set()) & RETRY_CODES):
                raise
            time.sleep(4)


def _wait_ready(container_id, tries=10):
    """컨테이너가 게시 가능한 상태가 될 때까지 잠깐 기다립니다."""
    for _ in range(tries):
        status = _call("GET", container_id, fields="status_code").get("status_code")
        if status in (None, "FINISHED"):
            return
        if status == "ERROR":
            raise InstagramError("인스타그램이 사진을 처리하지 못했어요.")
        time.sleep(1)


def _publish(container_id):
    _wait_ready(container_id)
    user = settings.IG_USER_ID
    return _call("POST", f"{user}/media_publish", creation_id=container_id)["id"]


def _dry_run(kind, urls, caption):
    fake_id = f"dryrun-{uuid.uuid4().hex[:10]}"
    log.info("[연습 모드] %s 게시 %s | %s | %s", kind, fake_id, urls, caption[:60])
    return fake_id


def publish_photo(image_url, caption="", story=False):
    """사진 한 장을 피드 또는 스토리에 올리고 게시물 id를 돌려줍니다."""
    if not is_configured():
        return _dry_run("스토리" if story else "피드", [image_url], caption)
    params = {"image_url": image_url}
    if story:
        params["media_type"] = "STORIES"  # 스토리는 캡션을 받지 않습니다.
    else:
        params["caption"] = caption
    container = _create_container(**params)
    return _publish(container)


def publish_carousel(image_urls, caption=""):
    """여러 장(2~10장)을 한 게시물로 묶어 피드에 올립니다."""
    image_urls = list(image_urls)[:MAX_CAROUSEL]
    if len(image_urls) == 1:
        return publish_photo(image_urls[0], caption)
    if not is_configured():
        return _dry_run("묶음", image_urls, caption)
    user = settings.IG_USER_ID
    children = [
        _call("POST", f"{user}/media", image_url=url, is_carousel_item="true")["id"]
        for url in image_urls
    ]
    container = _call(
        "POST",
        f"{user}/media",
        media_type="CAROUSEL",
        children=",".join(children),
        caption=caption,
    )["id"]
    return _publish(container)


def check():
    """인스타그램 토큰이 살아 있는지, 사용자 ID가 맞는지 확인합니다. (ok, 설명)을 돌려줍니다."""
    if not is_configured():
        missing = [k for k in ("IG_USER_ID", "IG_ACCESS_TOKEN") if not getattr(settings, k)]
        return False, f"{', '.join(missing)} 값이 비어 있어요. (연습 모드)"
    user_id = str(settings.IG_USER_ID).strip()
    try:
        info = _call("GET", user_id, fields="username")
    except InstagramError as exc:
        return False, f"{str(exc)[:300]} (주소: {graph_url()})"
    return True, f"정상 (@{info.get('username', '?')})"
