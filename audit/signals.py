from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import AuditLog
from .services import record_audit


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    record_audit(
        request=request, user=user, action="login_success",
        category=AuditLog.Category.AUTHENTICATION,
        description="Başarılı giriş.",
    )


@receiver(user_login_failed)
def audit_login_failed(sender, credentials, request, **kwargs):
    record_audit(
        request=request, username=str(credentials.get("username", "")),
        action="login_failed", category=AuditLog.Category.AUTHENTICATION,
        success=False, description="Başarısız giriş denemesi.",
    )


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    record_audit(
        request=request, user=user, action="logout",
        category=AuditLog.Category.AUTHENTICATION,
        description="Kullanıcı çıkış yaptı.",
    )

