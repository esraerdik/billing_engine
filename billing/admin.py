from django.contrib import admin
from django.core.exceptions import PermissionDenied

from .models import (
    ApprovalRequest,
    Apartment,
    ApartmentBillingLine,
    ApartmentComplex,
    ApartmentResident,
    BillingRun,
    ComplexAccess,
    MeterDevice,
    MeterAlert,
    MeterReading,
    MeterReadingLog,
)


class AppendOnlyModelAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ApartmentComplex)
class ApartmentComplexAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "created_at")
    search_fields = ("name", "address")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_deleted=False)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ComplexAccess)
class ComplexAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "complex", "granted_at")
    list_filter = ("complex",)
    search_fields = ("user__username", "complex__name")


class ApartmentResidentInline(admin.TabularInline):
    model = ApartmentResident
    extra = 0
    fields = ("name", "started_at", "ended_at")
    readonly_fields = ("created_at",)


@admin.register(Apartment)
class ApartmentAdmin(admin.ModelAdmin):
    list_display = (
        "unit_no",
        "complex",
        "area_m2",
        "is_active",
        "updated_at",
    )
    list_filter = ("complex", "is_active")
    search_fields = ("unit_no",)
    inlines = [ApartmentResidentInline]


@admin.register(ApartmentResident)
class ApartmentResidentAdmin(admin.ModelAdmin):
    list_display = ("name", "apartment", "started_at", "ended_at", "is_current")
    list_filter = ("apartment__complex",)
    search_fields = ("name", "apartment__unit_no")
    readonly_fields = ("created_at",)


@admin.register(MeterDevice)
class MeterDeviceAdmin(admin.ModelAdmin):
    list_display = (
        "modbus_address", "apartment", "status", "last_success_at",
        "last_failure_at", "total_retry_count", "is_active",
    )
    list_filter = ("status", "is_active", "apartment__complex")


@admin.register(MeterReading)
class MeterReadingAdmin(AppendOnlyModelAdmin):
    list_display = ("device", "raw_value", "read_at", "created_at")
    list_filter = ("device__apartment__complex",)
    readonly_fields = ("device", "raw_value", "read_at", "created_at")

    def save_model(self, request, obj, form, change):
        if change:
            raise PermissionDenied("Meter readings are append-only.")
        super().save_model(request, obj, form, change)


@admin.register(MeterReadingLog)
class MeterReadingLogAdmin(AppendOnlyModelAdmin):
    list_display = (
        "read_at", "complex", "apartment", "device_identifier",
        "energy_value", "status", "retry_number", "error_type",
    )
    list_filter = ("status", "error_type", "complex")
    search_fields = (
        "apartment__unit_no", "device_identifier", "error_description"
    )
    readonly_fields = [field.name for field in MeterReadingLog._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(MeterAlert)
class MeterAlertAdmin(admin.ModelAdmin):
    list_display = ("device", "severity", "is_active", "updated_at", "resolved_at")
    list_filter = ("severity", "is_active", "device__apartment__complex")
    readonly_fields = (
        "device", "severity", "message", "is_active",
        "created_at", "updated_at", "resolved_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ApartmentBillingLineInline(admin.TabularInline):
    model = ApartmentBillingLine
    extra = 0
    readonly_fields = (
        "apartment",
        "start_reading",
        "end_reading",
        "energy_consumed",
        "area_ratio",
        "energy_ratio",
        "fixed_share",
        "consumption_share",
        "total_payable",
        "status",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BillingRun)
class BillingRunAdmin(admin.ModelAdmin):
    list_display = (
        "complex",
        "period_year",
        "period_month",
        "window_start_date",
        "window_end_date",
        "total_bill",
        "recorded_at",
    )
    list_filter = ("complex", "period_year", "period_month")
    readonly_fields = (
        "complex",
        "period_year",
        "period_month",
        "window_start_date",
        "window_end_date",
        "total_bill",
        "total_fixed_amount",
        "total_consumption_amount",
        "total_area",
        "total_energy",
        "run_by",
        "recorded_at",
    )
    inlines = [ApartmentBillingLineInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ApartmentBillingLine)
class ApartmentBillingLineAdmin(admin.ModelAdmin):
    list_display = (
        "billing_run",
        "apartment",
        "energy_consumed",
        "total_payable",
        "status",
    )
    readonly_fields = (
        "billing_run",
        "apartment",
        "start_reading",
        "end_reading",
        "energy_consumed",
        "area_ratio",
        "energy_ratio",
        "fixed_share",
        "consumption_share",
        "total_payable",
        "status",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = (
        "complex",
        "window_start_date",
        "window_end_date",
        "status",
        "requested_by",
        "requested_at",
        "billing_run",
    )
    list_filter = ("status", "complex")
    readonly_fields = (
        "complex",
        "period_year",
        "period_month",
        "window_start_date",
        "window_end_date",
        "requested_by",
        "requested_at",
        "decided_by",
        "decided_at",
        "billing_run",
    )
