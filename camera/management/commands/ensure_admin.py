"""ADMIN_USERNAME / ADMIN_PASSWORD 환경 변수로 로그인 계정을 만들거나 비밀번호를 맞춥니다.

Render 무료 플랜에는 Shell이 없어 createsuperuser를 직접 실행할 수 없으므로,
배포할 때(build.sh) 이 명령이 자동으로 실행됩니다. 값이 없으면 아무것도 하지 않습니다.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "환경 변수로 로그인 계정을 준비합니다."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "").strip()
        password = os.environ.get("ADMIN_PASSWORD", "")
        if not username or not password:
            self.stdout.write("ADMIN_USERNAME / ADMIN_PASSWORD 가 없어 계정을 만들지 않았습니다.")
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username, defaults={"is_staff": True, "is_superuser": True}
        )
        user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(f"로그인 계정 '{username}' {'생성' if created else '갱신'} 완료")
