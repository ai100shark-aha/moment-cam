"""하루치 사진과 캡션을 모아 블로그에 붙여 넣을 초안을 만듭니다."""
from django.utils import timezone

from ..models import Photo


def photos_for(day):
    return Photo.objects.filter(taken_at__date=day).exclude(status=Photo.CANCELLED)


def build(day, photos):
    photos = list(photos)
    races = {p.race.name for p in photos if p.race}
    if races:
        title = f"{' · '.join(sorted(races))} 달리기 기록"
    else:
        title = f"{day.month}월 {day.day}일의 기록"

    lines, tags = [], []
    for photo in photos:
        when = timezone.localtime(photo.taken_at).strftime("%H:%M")
        text = photo.caption.strip() or "(사진)"
        extra = f" ({photo.race_line})" if photo.race_line else ""
        lines.append(f"[{when}] {text}{extra}")
        for tag in photo.hashtags.split():
            if tag not in tags:
                tags.append(tag)
    body = "\n\n".join(lines)
    if tags:
        body += "\n\n" + " ".join(tags[:15])
    return {"title": title, "body": body}
