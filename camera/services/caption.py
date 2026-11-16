"""Claude API로 사진을 보고 캡션·해시태그·사진 속 인원수를 받아옵니다.

한 번의 호출로 세 가지를 모두 받아 비용을 줄입니다.
API 키가 없으면 빈 결과를 돌려주고 앱은 그대로 동작합니다.
"""
import base64
import json
import logging
import re

from django.conf import settings

from . import images

log = logging.getLogger("camera")

PROMPT = """이 사진을 SNS에 올리려고 합니다. 아래 JSON 형식으로만 답하세요. 다른 말은 쓰지 마세요.

{{"caption": "한국어 캡션 한 문장(25자 안팎, 담백하게, 이모지 없이)", "hashtags": ["해시태그", "3~5개", "# 없이"], "people_count": 사진에 얼굴이 뚜렷이 보이는 사람 수(정수)}}

참고: {context}"""

EMPTY = {"caption": "", "hashtags": "", "people_count": None}


def is_configured():
    return bool(settings.ANTHROPIC_API_KEY)


def _parse(text):
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"JSON 없음: {text[:80]}")
    data = json.loads(match.group(0))
    tags = data.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    tags = ["#" + str(t).lstrip("#").replace(" ", "") for t in tags if str(t).strip("# ")]
    people = data.get("people_count")
    return {
        "caption": str(data.get("caption") or "").strip(),
        "hashtags": " ".join(tags[:5]),
        "people_count": int(people) if isinstance(people, (int, float)) else None,
    }


def analyze(image_bytes, mode="daily", race_name=""):
    """{'caption', 'hashtags', 'people_count'}를 돌려줍니다. 실패해도 예외를 내지 않습니다."""
    if not is_configured():
        return dict(EMPTY)
    try:
        import anthropic

        if mode == "race":
            context = f"달리기 대회({race_name or '레이스'}) 도중에 찍은 사진입니다."
        else:
            context = "일상에서 기억하고 싶은 순간을 찍은 사진입니다."
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=20)
        message = client.messages.create(
            model=settings.CAPTION_MODEL,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": base64.b64encode(
                                    images.small_jpeg(image_bytes)
                                ).decode(),
                            },
                        },
                        {"type": "text", "text": PROMPT.format(context=context)},
                    ],
                }
            ],
        )
        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        return _parse(text)
    except Exception as exc:  # 캡션이 없어도 게시는 계속되어야 합니다.
        log.warning("AI 캡션 실패: %s", exc)
        return dict(EMPTY)
