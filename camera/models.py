import uuid

from django.db import models
from django.utils import timezone


class AppSettings(models.Model):
    """게시 설정. 혼자 쓰는 앱이라 한 줄(pk=1)만 둡니다."""

    TARGET_FEED = "feed"
    TARGET_STORY = "story"
    TARGET_CHOICES = [(TARGET_FEED, "피드"), (TARGET_STORY, "스토리")]

    post_instagram = models.BooleanField("인스타그램 자동 게시", default=True)
    make_blog_draft = models.BooleanField("블로그 초안 만들기", default=True)
    daily_target = models.CharField(
        "일상 모드 게시 위치", max_length=10, choices=TARGET_CHOICES, default=TARGET_FEED
    )
    daily_batch = models.BooleanField("일상 모드: 모아서 한 번에", default=False)
    cancel_seconds = models.PositiveSmallIntegerField(
        "게시 전 취소 가능 시간(초)", default=3, help_text="0이면 매번 직접 확인"
    )
    group_check = models.BooleanField("단체 사진은 물어보기", default=True)
    offline_queue = models.BooleanField("신호 없으면 대기 후 올리기", default=True)
    ai_caption = models.BooleanField("AI 캡션 자동 작성", default=True)

    class Meta:
        verbose_name = verbose_name_plural = "게시 설정"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def as_dict(self):
        return {
            "post_instagram": self.post_instagram,
            "make_blog_draft": self.make_blog_draft,
            "daily_target": self.daily_target,
            "daily_batch": self.daily_batch,
            "cancel_seconds": self.cancel_seconds,
            "group_check": self.group_check,
            "offline_queue": self.offline_queue,
            "ai_caption": self.ai_caption,
        }


class RaceSession(models.Model):
    name = models.CharField("대회 이름", max_length=100)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = verbose_name_plural = "레이스"

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.finished_at is None

    @classmethod
    def active(cls):
        return cls.objects.filter(finished_at__isnull=True).first()


def photo_path(instance, filename):
    return f"photos/{timezone.localdate():%Y/%m/%d}/{uuid.uuid4().hex}.jpg"


class Photo(models.Model):
    MODE_DAILY = "daily"
    MODE_RACE = "race"
    MODE_CHOICES = [(MODE_DAILY, "일상"), (MODE_RACE, "레이스")]

    DRAFT = "draft"  # 올라왔고, 취소 가능 시간 안에 있음
    NEEDS_CONSENT = "needs_consent"  # 단체 사진: 확인 대기
    QUEUED = "queued"  # 모아서 올리기 대기
    POSTED = "posted"
    CANCELLED = "cancelled"
    FAILED = "failed"
    STATUS_CHOICES = [
        (DRAFT, "게시 대기"),
        (NEEDS_CONSENT, "확인 필요"),
        (QUEUED, "모으는 중"),
        (POSTED, "게시됨"),
        (CANCELLED, "취소됨"),
        (FAILED, "실패"),
    ]

    client_id = models.UUIDField(unique=True, default=uuid.uuid4)
    image = models.ImageField(upload_to=photo_path)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_DAILY)
    race = models.ForeignKey(
        RaceSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="photos"
    )
    taken_at = models.DateTimeField(default=timezone.now)

    caption = models.TextField(blank=True)
    hashtags = models.CharField(max_length=300, blank=True)
    people_count = models.PositiveSmallIntegerField(null=True, blank=True)

    distance_km = models.FloatField(null=True, blank=True)
    elapsed_seconds = models.PositiveIntegerField(null=True, blank=True)
    section = models.CharField(max_length=60, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    target = models.CharField(max_length=10, default=AppSettings.TARGET_FEED)
    ig_media_id = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["taken_at"]
        verbose_name = verbose_name_plural = "사진"

    def __str__(self):
        return f"{self.taken_at:%m-%d %H:%M} {self.caption[:20]}"

    @property
    def full_caption(self):
        return "\n".join(p for p in [self.caption.strip(), self.hashtags.strip()] if p)

    @property
    def race_line(self):
        """레이스 정보 한 줄 (예: 28.4km · 2:41:05 · CP3→CP4)."""
        parts = []
        if self.distance_km is not None:
            parts.append(f"{self.distance_km:.1f}km")
        if self.elapsed_seconds is not None:
            h, rem = divmod(self.elapsed_seconds, 3600)
            m, s = divmod(rem, 60)
            parts.append(f"{h}:{m:02d}:{s:02d}")
        if self.section:
            parts.append(self.section)
        return " · ".join(parts)

    def as_dict(self):
        return {
            "id": self.pk,
            "status": self.status,
            "status_label": self.get_status_display(),
            "caption": self.caption,
            "hashtags": self.hashtags,
            "people_count": self.people_count,
            "target": self.target,
            "image": self.image.url,
            "error": self.error,
        }
