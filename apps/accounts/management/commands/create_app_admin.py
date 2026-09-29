"""Create the first application administrator without embedding a default credential."""

import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.common.enums import UserRole


class Command(BaseCommand):
    help = "Create the initial ADMIN account; existing accounts are never overwritten."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument("--display-name")
        parser.add_argument("--password")

    def handle(self, *args, **options):
        username = (options["username"] or input("管理员用户名: ")).strip()
        display_name = (options["display_name"] or username).strip()
        password = options["password"] or getpass.getpass("管理员口令: ")
        if not username or not password:
            raise CommandError("用户名和口令不能为空")
        existing = User.objects.filter(username=username).first()
        if existing:
            if existing.role != UserRole.ADMIN:
                raise CommandError("同名账号已存在且不是管理员；命令不会覆盖现有账号")
            self.stdout.write(self.style.WARNING("管理员账号已存在，未修改任何资料或口令"))
            return
        User.objects.create_superuser(
            username=username,
            password=password,
            display_name=display_name,
            role=UserRole.ADMIN,
        )
        self.stdout.write(self.style.SUCCESS(f"管理员 {username} 已创建"))
