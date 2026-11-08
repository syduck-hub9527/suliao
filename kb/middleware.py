"""
免登录模式：每个访问都自动以“站长”身份进入，不需要登录页。

只在 settings.SINGLE_USER_MODE 为 True 时生效；settings 里已经保证此时网站只能本机访问。
"""

from django.conf import settings
from django.contrib.auth import get_user_model, login

OWNER_USERNAME = "owner"


def get_owner():
    User = get_user_model()
    user, created = User.objects.get_or_create(
        username=OWNER_USERNAME,
        defaults={"is_staff": True, "is_superuser": True, "is_active": True},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    elif not (user.is_staff and user.is_superuser and user.is_active):
        user.is_staff = user.is_superuser = user.is_active = True
        user.save(update_fields=["is_staff", "is_superuser", "is_active"])
    return user


class SingleUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "SINGLE_USER_MODE", False) and not request.user.is_authenticated:
            login(request, get_owner(), backend="django.contrib.auth.backends.ModelBackend")
        return self.get_response(request)
