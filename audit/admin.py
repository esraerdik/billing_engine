from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "username", "category", "action", "success", "object_repr")
    list_filter = ("category", "action", "success", "occurred_at")
    search_fields = ("username", "object_repr", "object_id", "description")
    readonly_fields = [field.name for field in AuditLog._meta.fields]
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
