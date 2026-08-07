import logging

from django.db import DatabaseError

from accounts.models import UserProfile

from .models import AuditLog

logger = logging.getLogger(__name__)


def get_client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    value = forwarded.split(",", 1)[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return value or None


def _role_for(user) -> str:
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    profile = getattr(user, "profile", None)
    if profile:
        return profile.role
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return UserProfile.Role.ADMIN
    return UserProfile.Role.USER


def record_audit(
    *,
    action: str,
    category: str,
    request=None,
    user=None,
    success: bool = True,
    object_type: str = "",
    object_id=None,
    object_repr: str = "",
    description: str = "",
    metadata: dict | None = None,
    username: str = "",
) -> AuditLog | None:
    """Audit yazımındaki bir sorun ana iş akışını bozmasın."""
    actor = user or getattr(request, "user", None)
    authenticated = bool(actor and getattr(actor, "is_authenticated", False))
    try:
        return AuditLog.objects.create(
            user=actor if authenticated and getattr(actor, "pk", None) else None,
            username=(getattr(actor, "username", "") if authenticated else username)[:150],
            user_role=_role_for(actor),
            action=action,
            category=category,
            ip_address=get_client_ip(request),
            success=success,
            object_type=object_type,
            object_id="" if object_id is None else str(object_id),
            object_repr=str(object_repr)[:255],
            description=description,
            metadata=metadata or {},
        )
    except (DatabaseError, TypeError, ValueError):
        logger.exception("Denetim kaydı veritabanına yazılamadı: %s", action)
        return None


def record_request(request, action: str, category: str, **kwargs):
    return record_audit(request=request, action=action, category=category, **kwargs)
