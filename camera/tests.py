import io
import shutil
import tempfile
import uuid
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import AppSettings, Photo, RaceSession
from .services import caption, images, instagram

MEDIA = tempfile.mkdtemp()


def jpeg(width=1080, height=1350):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (40, 60, 80)).save(buf, "JPEG")
    return buf.getvalue()


def upload_file(**size):
    return SimpleUploadedFile("p.jpg", jpeg(**size), content_type="image/jpeg")


AI = {"caption": "제주 바다 위로 지는 노을", "hashtags": "#제주 #노을", "people_count": 0}


@override_settings(
    MEDIA_ROOT=MEDIA, ANTHROPIC_API_KEY="", IG_USER_ID="", IG_ACCESS_TOKEN="",
    PUBLIC_BASE_URL="https://example.test",
)
class FlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.client.force_login(User.objects.create_user("runner", password="pw"))

    def upload(self, ai=AI, **data):
        with mock.patch.object(caption, "analyze", return_value=dict(ai)):
            return self.client.post(
                reverse("api_upload"), {"image": upload_file(), **data}
            )

    def test_pages_need_login(self):
        self.client.logout()
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.post(reverse("api_upload")).status_code, 401)

    def test_pages_render(self):
        self.upload()
        for name in ("camera", "today", "settings", "manifest", "sw"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_daily_photo_gets_caption_then_posts_to_feed(self):
        data = self.upload().json()
        self.assertEqual(data["status"], Photo.DRAFT)
        self.assertEqual(data["caption"], AI["caption"])
        self.assertEqual(data["cancel_seconds"], 3)
        with mock.patch.object(instagram, "publish_photo", return_value="m1") as pub:
            res = self.client.post(
                reverse("api_publish", args=[data["id"]]),
                {"caption": "고친 캡션"}, content_type="application/json",
            )
        self.assertEqual(res.json()["status"], Photo.POSTED)
        url, text = pub.call_args[0]
        self.assertTrue(url.startswith("https://example.test/media/photos/"))
        self.assertEqual(text, "고친 캡션\n#제주 #노을")

    def test_same_photo_uploaded_twice_is_saved_once(self):
        cid = str(uuid.uuid4())
        first = self.upload(client_id=cid).json()
        second = self.upload(client_id=cid).json()
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(Photo.objects.count(), 1)

    def test_group_photo_waits_for_consent(self):
        data = self.upload(ai={**AI, "people_count": 3}).json()
        self.assertEqual(data["status"], Photo.NEEDS_CONSENT)

    def test_phone_face_count_also_triggers_consent(self):
        data = self.upload(client_faces="2").json()
        self.assertEqual(data["status"], Photo.NEEDS_CONSENT)

    def test_group_check_off_posts_normally(self):
        s = AppSettings.load()
        s.group_check = False
        s.save()
        data = self.upload(ai={**AI, "people_count": 3}).json()
        self.assertEqual(data["status"], Photo.DRAFT)

    def test_batch_mode_collects_instead_of_posting(self):
        s = AppSettings.load()
        s.daily_batch = True
        s.save()
        self.assertEqual(self.upload().json()["status"], Photo.QUEUED)

    def test_cancel_stops_posting(self):
        data = self.upload().json()
        res = self.client.post(reverse("api_cancel", args=[data["id"]]))
        self.assertEqual(res.json()["status"], Photo.CANCELLED)

    def test_race_photo_goes_to_story_with_stats(self):
        self.client.post(
            reverse("api_race_start"), {"name": "제주 마라톤"}, content_type="application/json"
        )
        data = self.upload(
            mode="race", distance_km="28.44", elapsed_seconds="9665", section="CP3→CP4"
        ).json()
        self.assertEqual(data["target"], "story")
        self.assertEqual(data["race_line"], "28.4km · 2:41:05 · CP3→CP4")
        with mock.patch.object(instagram, "publish_photo", return_value="s1") as pub:
            self.client.post(reverse("api_publish", args=[data["id"]]))
        self.assertTrue(pub.call_args.kwargs["story"])
        self.assertEqual(Photo.objects.get().race.name, "제주 마라톤")

    def test_finish_then_bundle_best_photos_to_feed(self):
        self.client.post(
            reverse("api_race_start"), {"name": "제주 마라톤"}, content_type="application/json"
        )
        ids = [self.upload(mode="race").json()["id"] for _ in range(3)]
        self.client.post(reverse("api_race_finish"))
        self.assertIsNone(RaceSession.active())
        with mock.patch.object(instagram, "publish_carousel", return_value="c1") as pub:
            res = self.client.post(
                reverse("api_bundle"), {"ids": ids, "caption": "완주!"},
                content_type="application/json",
            )
        self.assertEqual(res.json()["count"], 3)
        self.assertEqual(len(pub.call_args[0][0]), 3)
        self.assertEqual(Photo.objects.filter(status=Photo.POSTED, target="feed").count(), 3)

    def test_instagram_failure_is_recorded_and_can_retry(self):
        data = self.upload().json()
        url = reverse("api_publish", args=[data["id"]])
        with mock.patch.object(
            instagram, "publish_photo", side_effect=instagram.InstagramError("토큰 만료")
        ):
            res = self.client.post(url)
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json()["status"], Photo.FAILED)
        with mock.patch.object(instagram, "publish_photo", return_value="m2"):
            self.assertEqual(self.client.post(url).json()["status"], Photo.POSTED)

    def test_practice_mode_without_instagram_account(self):
        data = self.upload().json()
        res = self.client.post(reverse("api_publish", args=[data["id"]]))
        self.assertEqual(res.json()["status"], Photo.POSTED)
        self.assertTrue(Photo.objects.get().ig_media_id.startswith("dryrun-"))

    def test_blog_draft_lists_captions_in_order(self):
        self.upload()
        html = self.client.get(reverse("today")).content.decode()
        self.assertIn("제주 바다 위로 지는 노을", html)
        self.assertIn("블로그 초안", html)

    def test_diagnose_reports_missing_keys(self):
        checks = self.client.post(reverse("api_diagnose")).json()["checks"]
        self.assertEqual([c["ok"] for c in checks], [False, False, True])
        self.assertIn("ANTHROPIC_API_KEY", checks[0]["detail"])

    @override_settings(IG_USER_ID="111", IG_ACCESS_TOKEN="t")
    def test_diagnose_spots_wrong_instagram_user_id(self):
        with mock.patch.object(
            instagram, "_call", return_value={"user_id": "222", "username": "runner"}
        ):
            ok, text = instagram.check()
        self.assertFalse(ok)
        self.assertIn("222", text)

    def test_settings_save(self):
        self.client.post(
            reverse("settings"),
            {"daily_target": "story", "daily_batch": "", "cancel_seconds": "5", "ai_caption": "on"},
        )
        s = AppSettings.load()
        self.assertEqual((s.daily_target, s.cancel_seconds), ("story", 5))
        self.assertTrue(s.ai_caption)
        self.assertFalse(s.group_check)


class ServiceTests(TestCase):
    def test_tall_story_photo_is_cropped_for_feed(self):
        out = images.feed_safe(jpeg(1080, 1920))
        w, h = Image.open(io.BytesIO(out)).size
        self.assertAlmostEqual(w / h, 4 / 5, places=2)
        self.assertIsNone(images.feed_safe(jpeg(1080, 1350)))

    def test_ai_answer_parsing(self):
        got = caption._parse(
            '```json\n{"caption": "노을", "hashtags": ["제주", "#노을 맛집"], "people_count": 2}\n```'
        )
        self.assertEqual(got, {"caption": "노을", "hashtags": "#제주 #노을맛집", "people_count": 2})

    @override_settings(ANTHROPIC_API_KEY="")
    def test_no_api_key_gives_empty_caption(self):
        self.assertEqual(caption.analyze(jpeg())["caption"], "")
