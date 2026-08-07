from .models import AuditLog
from .services import record_audit


class AuditExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        record_audit(
            request=request,
            action="unexpected_error",
            category=AuditLog.Category.SYSTEM,
            success=False,
            object_type=exception.__class__.__name__,
            description=str(exception)[:1000] or "Beklenmeyen sistem hatası.",
            metadata={"path": request.path, "method": request.method},
        )
        return None

