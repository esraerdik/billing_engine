import logging
from datetime import date
from decimal import InvalidOperation
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import CharField, Q
from django.db.models.functions import Cast
from django.http import FileResponse, Http404, HttpResponse
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

logger = logging.getLogger(__name__)

from accounts.exceptions import (
    AdminDeactivationForbiddenError,
    LastAdminDeletionError,
    LastActiveAdminError,
    UsernameAlreadyExistsError,
)
from accounts.models import UserProfile
from accounts.services import (
    create_user,
    delete_user,
    is_admin_user,
    list_deleted_users,
    list_users,
    restore_user,
    update_user,
)
from billing.exceptions import (
    BillingWindowError,
    ComplexAccessDeniedError,
    DuplicateApartmentUnitError,
    InvalidEnergyReadingError,
)
from billing.models import (
    Apartment,
    ApartmentBillingLine,
    ApartmentComplex,
    ApprovalRequest,
    BillingRun,
    MeterDevice,
    MeterReadingLog,
)
from billing.services import (
    approve_request,
    create_apartment,
    create_complex,
    delete_apartment,
    delete_complex,
    deny_request,
    get_apartment_current_resident_name,
    list_accessible_complexes,
    list_active_apartments,
    list_apartments,
    list_complex_access_ids,
    list_complexes,
    list_deleted_complexes,
    list_pending_approval_requests,
    run_billing_or_request_approval,
    set_complex_access,
    update_apartment,
    update_complex,
    restore_complex,
)
from domain.exceptions import (
    AdminApprovalRequiredError,
    ZeroAreaError,
    ZeroTotalEnergyError,
)
from invoice_pdf.service import build_zip_for_run, get_invoice_path_for_apartment
from audit.labels import (
    build_action_choices,
    get_action_codes,
    get_action_key,
    get_action_label,
)
from audit.models import AuditLog
from audit.services import record_request
from billing.meter_reading import list_active_meter_alerts

# Admin paneline ve altındaki işlemlere (bina/kullanıcı ekleme-düzenleme-
# silme, onay/red) sadece Admin rollü kullanıcılar erişebilir.
# `login_required` zaten oturum açmamışları login sayfasına yönlendiriyor;
# bu, oturumu açık ama rolü "user" olan birinin admin URL'lerine doğrudan
# erişimini engelleyen ek katmandır.
admin_required = user_passes_test(is_admin_user, login_url="login")


def user_area_required(view_func):
    """Daire yönetimi (ekle/düzenle/sil) YALNIZCA "user" rollü hesaplara
    açıktır — iş kuralı gereği admin, daire yönetimi yapamaz.

    Katmanlar:
      - Oturum açmamışlar → giriş sayfasına (`login_required`).
      - Admin rollü hesaplar → kendi paneline (`admin_dashboard`);
        daire yönetimi admin panelinden tamamen kaldırıldığı için bu
        uç noktalar onlara kapalıdır.
      - "user" rollüler → devam eder; bina bazlı erişim kontrolü ayrıca
        servis katmanında yapılır (bkz. `billing.services._ensure_complex_access`).
    """

    @login_required(login_url="login")
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if is_admin_user(request.user):
            return redirect("admin_dashboard")
        return view_func(request, *args, **kwargs)

    return _wrapped


def _redirect_to_user_dashboard(complex_id=None):
    """Daire işlemleri sonrası kullanıcıyı, üzerinde çalıştığı bina
    seçiliyken user paneline geri gönderir."""
    url = reverse("user_dashboard")
    if complex_id:
        url = f"{url}?complex_id={complex_id}"
    return redirect(url)


def _ensure_apartment_access(user, apartment) -> None:
    """Kullanıcının, dairenin ait olduğu binaya erişim yetkisi yoksa 404
    fırlatır — başka bir kullanıcıya ait dairenin VAR OLDUĞUNU bile ele
    vermemek için (bkz. `_ensure_billing_run_access` ile aynı ilke)."""
    accessible_ids = {c.id for c in list_accessible_complexes(user)}
    if apartment.complex_id not in accessible_ids:
        raise Http404("Bu daireye erişim yetkiniz yok.")


@login_required(login_url="login")
def user_dashboard(request):
    accessible_complexes = list_accessible_complexes(request.user)

    # Daire yönetimi (ekle/düzenle/sil) yalnızca "user" rollü hesaplara
    # açıktır; admin bir kullanıcı panelini görüntülese bile bu bölümü
    # görmez (uç noktalar da `user_area_required` ile korunur).
    can_manage_apartments = not is_admin_user(request.user)

    if not accessible_complexes:
        context = {
            "results": None,
            "bill": "",
            "window_start": "",
            "window_end": "",
            "apartments": [],
            "manage_apartments": [],
            "can_manage_apartments": can_manage_apartments,
            "complex": None,
            "complexes": [],
            "meter_alerts": [],
            "error": (
                "Size atanmış bir apartman bulunmuyor. Lütfen admin ile "
                "iletişime geçin."
            ),
        }
        return render(request, "dashboard/user_dashboard.html", context)

    # Kullanıcının erişebildiği apartmanlar arasından hangisi üzerinde
    # çalışılacağı `complex_id` (GET veya POST) ile seçilir. Apartman
    # seçici zaten sadece yetkili apartmanları listelediği için normal
    # kullanımda geçersiz bir id gelmez; GET'te (sayfa görüntüleme)
    # geçersiz/eksik id sessizce ilk apartmana düşer, ama bir POST
    # (hesaplama gönderimi) yetkisiz bir `complex_id` içeriyorsa —
    # formun manipüle edildiği anlamına gelir — açıkça reddedilir.
    accessible_by_id = {c.id: c for c in accessible_complexes}
    raw_complex_id = request.POST.get("complex_id") or request.GET.get("complex_id")
    try:
        selected_id = int(raw_complex_id) if raw_complex_id else None
    except ValueError:
        selected_id = None

    complex_obj = accessible_by_id.get(selected_id) if selected_id else None
    if complex_obj is None:
        complex_obj = accessible_complexes[0]

    apartment_rows = list_active_apartments(complex_obj.id)

    context = {
        "results": None,
        "bill": "",
        "window_start": "",
        "window_end": "",
        "apartments": apartment_rows,
        # Daire yönetimi tablosu: seçili binadaki TÜM daireler (aktif/pasif).
        "manage_apartments": (
            list_apartments(complex_obj.id) if can_manage_apartments else []
        ),
        "can_manage_apartments": can_manage_apartments,
        "complex": complex_obj,
        "complexes": accessible_complexes,
        "error": None,
        "billing_run_id": None,
        "meter_alerts": list_active_meter_alerts(
            complex_ids=[c.id for c in accessible_complexes]
        ),
    }

    if request.method == "POST":
        if selected_id is not None and selected_id not in accessible_by_id:
            context["error"] = "Seçilen apartmana erişim yetkiniz bulunmuyor."
            return render(request, "dashboard/user_dashboard.html", context)

        total_bill = float(request.POST.get("bill"))
        window_start = date.fromisoformat(request.POST["window_start"])
        window_end = date.fromisoformat(request.POST["window_end"])

        # Enerji artık tek bir alan değil, kümülatif sayaç mantığıyla
        # (ileride Modbus'la uyumlu) "İlk Enerji" (başlangıç endeksi) ve
        # "Son Enerji" (bitiş endeksi) çifti olarak girilir; tüketim bu
        # ikisinin farkı olarak `billing.services._build_domain_apartments`
        # içinde hesaplanır — burada sadece ham girdi toplanır.
        manual_energy: dict[int, tuple[float, float]] = {}
        incomplete_pair_error: str | None = None
        for row in apartment_rows:
            raw_start = request.POST.get(f"energy_start_{row.apartment_id}")
            raw_end = request.POST.get(f"energy_end_{row.apartment_id}")
            has_start = raw_start is not None and raw_start != ""
            has_end = raw_end is not None and raw_end != ""

            if has_start and has_end:
                manual_energy[row.apartment_id] = (float(raw_start), float(raw_end))
            elif has_start or has_end:
                incomplete_pair_error = (
                    f"“{row.unit_no}” dairesi için İlk Enerji ve Son Enerji "
                    "birlikte girilmelidir."
                )

        if incomplete_pair_error is not None:
            context["error"] = incomplete_pair_error
            context["bill"] = request.POST.get("bill", "")
            context["window_start"] = request.POST.get("window_start", "")
            context["window_end"] = request.POST.get("window_end", "")
            return render(request, "dashboard/user_dashboard.html", context)

        try:
            billing_run, summary = run_billing_or_request_approval(
                complex_id=complex_obj.id,
                user=request.user,
                window_start=window_start,
                window_end=window_end,
                total_bill=total_bill,
                manual_energy=manual_energy or None,
            )
            # `ApartmentBillingResult.apartment_id` (domain katmanı) aslında
            # `Apartment.pk`'dir — kullanıcıya gösterilecek gerçek daire
            # numarası (`unit_no`) değildir (PDF bunu `ApartmentBillingLine.
            # apartment.unit_no`'dan okur, bkz. invoice_pdf/service.py). Sonuç
            # listesi/sırası/değerleri değişmeden, template'e sadece görünüm
            # için `unit_no` eklenmiş bir kopya geçiriyoruz.
            unit_no_by_apartment_id = {
                row.apartment_id: row.unit_no for row in apartment_rows
            }
            context["results"] = [
                {
                    "apartment_id": result.apartment_id,
                    "unit_no": unit_no_by_apartment_id.get(result.apartment_id),
                    "fixed_share": result.fixed_share,
                    "consumption_share": result.consumption_share,
                    "total_payable": result.total_payable,
                }
                for result in summary.results
            ]
            context["billing_run_id"] = billing_run.id
            is_rebilling = hasattr(billing_run, "approval_request")
            record_request(
                request,
                action="rebilling" if is_rebilling else "billing_create",
                category=AuditLog.Category.BILLING,
                object_type="BillingRun",
                object_id=billing_run.id,
                object_repr=f"{complex_obj.name} {window_start}–{window_end}",
                description="Faturalandırma başarıyla tamamlandı.",
            )

        except ComplexAccessDeniedError as exc:
            context["error"] = str(exc)

        except BillingWindowError as exc:
            context["error"] = str(exc)

        except InvalidEnergyReadingError as exc:
            context["error"] = str(exc)

        except AdminApprovalRequiredError:
            # Bu aralık daha önce faturalandırılmış bir dönemle çakışıyor
            # (kısmi çakışma dâhil); doğrudan hesaplama yapılamaz. Servis
            # katmanı otomatik olarak bir yeniden faturalandırma talebi
            # oluşturup admin paneline düşürdü (bkz.
            # billing.services.run_billing_or_request_approval).
            context["error"] = (
                "Seçtiğiniz tarih aralığı daha önce faturalandırılmış bir "
                "dönemle çakışıyor. Yeniden faturalandırma talebiniz "
                "oluşturuldu; hesaplamanın çalışabilmesi için admin onayı "
                "gerekmektedir."
            )
            approval = (
                complex_obj.approval_requests.filter(requested_by=request.user)
                .order_by("-requested_at")
                .first()
            )
            record_request(
                request,
                action="rebilling_request_create",
                category=AuditLog.Category.BILLING,
                object_type="ApprovalRequest",
                object_id=getattr(approval, "id", None),
                object_repr=f"{complex_obj.name} {window_start}–{window_end}",
                description="Yeniden faturalandırma talebi oluşturuldu.",
            )

        except ZeroAreaError as exc:
            context["error"] = str(exc)

        except ZeroTotalEnergyError as exc:
            context["error"] = str(exc)

        context["bill"] = total_bill
        context["window_start"] = window_start.isoformat()
        context["window_end"] = window_end.isoformat()

    return render(request, "dashboard/user_dashboard.html", context)


@login_required(login_url="login")
@admin_required
def admin_dashboard(request):
    users = list_users()
    for u in users:
        u.is_protected_admin = is_admin_user(u)
        if u.is_protected_admin:
            u.complex_label = "Tümü"
        else:
            names = [c.name for c in list_accessible_complexes(u)]
            u.complex_label = ", ".join(names) if names else "—"

    context = {
        "requests": list_pending_approval_requests(),
        "complexes": list_complexes(),
        "users": users,
        "roles": UserProfile.Role.choices,
        "meter_alerts": list_active_meter_alerts(),
    }
    return render(request, "dashboard/admin_dashboard.html", context)


@login_required(login_url="login")
@admin_required
def deleted_users(request):
    return render(
        request,
        "dashboard/deleted_users.html",
        {"deleted_users": list_deleted_users()},
    )


@login_required(login_url="login")
@admin_required
def restore_deleted_user(request, user_id):
    if request.method == "POST":
        target_user = get_object_or_404(
            User.objects.select_related("profile"),
            pk=user_id,
            profile__is_deleted=True,
        )
        username = target_user.username
        restored = restore_user(user_id)
        record_request(
            request,
            action="user_restored",
            category=AuditLog.Category.USER,
            object_type="User",
            object_id=restored.id,
            object_repr=restored.username,
            description="Kullanıcı geri yüklendi.",
        )
        messages.success(request, f"Kullanıcı “{username}” geri yüklendi.")
    return redirect("deleted_users")


@login_required(login_url="login")
@admin_required
def deleted_complexes(request):
    return render(
        request,
        "dashboard/deleted_complexes.html",
        {"deleted_complexes": list_deleted_complexes()},
    )


@login_required(login_url="login")
@admin_required
def restore_deleted_complex(request, complex_id):
    if request.method == "POST":
        complex_obj = get_object_or_404(
            ApartmentComplex, pk=complex_id, is_deleted=True
        )
        name = complex_obj.name
        restored = restore_complex(complex_id)
        record_request(
            request,
            action="complex_restored",
            category=AuditLog.Category.COMPLEX,
            object_type="ApartmentComplex",
            object_id=restored.id,
            object_repr=restored.name,
            description="Apartman geri yüklendi.",
        )
        messages.success(request, f"“{name}” geri yüklendi.")
    return redirect("deleted_complexes")


def _audit_id_values(queryset):
    """Sayısal ilişkisel kimlikleri AuditLog.object_id ile aynı tipe çevirir."""
    return queryset.annotate(
        audit_object_id=Cast("id", output_field=CharField())
    ).values("audit_object_id")


def _filter_audit_logs_by_complex(logs, complex_id: int):
    """Bir apartmana doğrudan veya ilişkili kayıt üzerinden ait logları süzer."""
    apartment_ids = _audit_id_values(
        Apartment.objects.filter(complex_id=complex_id)
    )
    billing_run_ids = _audit_id_values(
        BillingRun.objects.filter(complex_id=complex_id)
    )
    approval_request_ids = _audit_id_values(
        ApprovalRequest.objects.filter(complex_id=complex_id)
    )
    meter_device_ids = _audit_id_values(
        MeterDevice.objects.filter(apartment__complex_id=complex_id)
    )

    return logs.filter(
        Q(object_type="ApartmentComplex", object_id=str(complex_id))
        | Q(object_type="Apartment", object_id__in=apartment_ids)
        | Q(object_type="ApartmentBillingLine", object_id__in=apartment_ids)
        | Q(object_type="BillingRun", object_id__in=billing_run_ids)
        | Q(object_type="ApprovalRequest", object_id__in=approval_request_ids)
        | Q(object_type="MeterDevice", object_id__in=meter_device_ids)
        | Q(metadata__complex_id=complex_id)
    )


@login_required(login_url="login")
@admin_required
def audit_logs(request):
    logs = AuditLog.objects.select_related("user")
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))
    user_id = request.GET.get("user")
    action = request.GET.get("action", "")
    success = request.GET.get("success", "")
    complex_id = request.GET.get("complex", "")
    if start_date:
        logs = logs.filter(occurred_at__date__gte=start_date)
    if end_date:
        logs = logs.filter(occurred_at__date__lte=end_date)
    if user_id:
        logs = logs.filter(user_id=user_id)
    if action:
        logs = logs.filter(action__in=get_action_codes(action))
    if success in {"true", "false"}:
        logs = logs.filter(success=success == "true")
    if complex_id:
        try:
            logs = _filter_audit_logs_by_complex(logs, int(complex_id))
        except (TypeError, ValueError):
            logs = logs.none()

    filter_params = request.GET.copy()
    filter_params.pop("page", None)
    page = Paginator(logs.order_by("-occurred_at", "-id"), 50).get_page(
        request.GET.get("page")
    )
    for log in page.object_list:
        log.display_action = get_action_label(log.action)

    action_values = AuditLog.objects.order_by("action").values_list(
        "action", flat=True
    ).distinct()
    action_choices = build_action_choices(action_values)
    return render(
        request,
        "dashboard/audit_logs.html",
        {
            "page": page,
            "users": list_users(),
            "complexes": list_complexes(include_deleted=True),
            "actions": action_choices,
            "selected_action": get_action_key(action) if action else "",
            "filters": request.GET,
            "filter_query": filter_params.urlencode(),
        },
    )


@login_required(login_url="login")
@admin_required
def meter_reading_history(request):
    history = MeterReadingLog.objects.select_related(
        "device", "apartment", "complex"
    )
    start_date = parse_date(request.GET.get("start_date", ""))
    end_date = parse_date(request.GET.get("end_date", ""))
    complex_id = request.GET.get("complex")
    status = request.GET.get("status", "")
    if start_date:
        history = history.filter(read_at__date__gte=start_date)
    if end_date:
        history = history.filter(read_at__date__lte=end_date)
    if complex_id:
        history = history.filter(complex_id=complex_id)
    if status:
        history = history.filter(status=status)
    page = Paginator(history.order_by("-read_at", "-id"), 50).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "dashboard/meter_reading_history.html",
        {
            "page": page,
            "complexes": list_complexes(),
            "statuses": MeterReadingLog.Status.choices,
            "filters": request.GET,
        },
    )
@login_required(login_url="login")
@admin_required
def approve(request, request_id):
    approval = get_object_or_404(
        ApprovalRequest.objects.select_related("complex"),
        pk=request_id,
        complex__is_deleted=False,
    )
    approve_request(request_id, request.user)
    record_request(
        request, action="billing_approval", category=AuditLog.Category.BILLING,
        object_type="ApprovalRequest", object_id=approval.id,
        object_repr=str(approval), description="Yeniden faturalandırma talebi onaylandı.",
    )
    return redirect("admin_dashboard")


@login_required(login_url="login")
@admin_required
def reject(request, request_id):
    approval = get_object_or_404(
        ApprovalRequest.objects.select_related("complex"),
        pk=request_id,
        complex__is_deleted=False,
    )
    deny_request(request_id, request.user)
    record_request(
        request, action="billing_rejection", category=AuditLog.Category.BILLING,
        object_type="ApprovalRequest", object_id=approval.id,
        object_repr=str(approval), description="Yeniden faturalandırma talebi reddedildi.",
    )
    return redirect("admin_dashboard")


@login_required(login_url="login")
@admin_required
def add_complex(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        address = request.POST.get("address", "").strip()
        if not name:
            messages.error(
                request,
                "Bina adı boş olamaz.",
                extra_tags="field-name",
            )
        else:
            complex_obj = create_complex(name=name, address=address)
            record_request(
                request, action="complex_create", category=AuditLog.Category.COMPLEX,
                object_type="ApartmentComplex", object_id=complex_obj.id,
                object_repr=complex_obj.name, description="Bina oluşturuldu.",
            )
            messages.success(request, f"“{name}” eklendi.")
    return redirect("admin_dashboard")


@login_required(login_url="login")
@admin_required
def edit_complex(request, complex_id):
    complex_obj = get_object_or_404(
        ApartmentComplex, pk=complex_id, is_deleted=False
    )
    if request.method == "GET":
        return render(
            request,
            "dashboard/complex_edit.html",
            {"complex": complex_obj},
        )

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        address = request.POST.get("address", "").strip()
        if not name:
            messages.error(
                request,
                "Bina adı boş olamaz.",
                extra_tags="field-name",
            )
        else:
            complex_obj = update_complex(
                complex_id=complex_id, name=name, address=address
            )
            record_request(
                request, action="complex_update", category=AuditLog.Category.COMPLEX,
                object_type="ApartmentComplex", object_id=complex_obj.id,
                object_repr=complex_obj.name, description="Bina düzenlendi.",
            )
            messages.success(request, f"“{name}” güncellendi.")
    return redirect("admin_dashboard")


@user_area_required
def add_apartment(request):
    complex_id = request.POST.get("complex_id")
    if request.method == "POST":
        unit_no = request.POST.get("unit_no", "").strip()
        block = request.POST.get("block", "").strip()
        area_m2 = request.POST.get("area_m2")
        resident_name = request.POST.get("resident_name", "").strip()

        if not (complex_id and unit_no and area_m2):
            missing_field = (
                "complex_id" if not complex_id else "unit_no" if not unit_no else "area_m2"
            )
            messages.error(
                request,
                "Bina, daire no ve alan alanları zorunludur.",
                extra_tags=f"field-{missing_field}",
            )
        else:
            try:
                apartment = create_apartment(
                    user=request.user,
                    complex_id=int(complex_id),
                    unit_no=unit_no,
                    area_m2=float(area_m2),
                    block=block or None,
                    resident_name=resident_name or None,
                )
                record_request(
                    request, action="apartment_create", category=AuditLog.Category.APARTMENT,
                    object_type="Apartment", object_id=apartment.id,
                    object_repr=str(apartment), description="Daire eklendi.",
                )
                messages.success(request, f"Daire “{unit_no}” eklendi.")
            except ComplexAccessDeniedError as exc:
                messages.error(
                    request,
                    str(exc),
                    extra_tags="field-complex_id",
                )
            except DuplicateApartmentUnitError as exc:
                messages.error(request, str(exc), extra_tags="field-unit_no")
            except IntegrityError:
                # Ek güvenlik ağı: eşzamanlı iki istek aynı numarayı üstteki
                # kontrolden hemen sonra göndermeye çalışırsa veritabanı
                # kısıtı burada devreye girer — 500 sayfasına asla düşülmez.
                messages.error(
                    request,
                    "Bu daire numarası zaten kullanılmaktadır. Lütfen "
                    "farklı bir daire numarası giriniz.",
                    extra_tags="field-unit_no",
                )
            except (ValueError, InvalidOperation):
                messages.error(
                    request,
                    "Alan (m²) sayısal olmalıdır.",
                    extra_tags="field-area_m2",
                )
    return _redirect_to_user_dashboard(complex_id)


@user_area_required
def edit_apartment(request, apartment_id):
    apartment = get_object_or_404(
        Apartment.objects.select_related("complex"), pk=apartment_id
    )
    _ensure_apartment_access(request.user, apartment)

    if request.method == "POST":
        complex_id = request.POST.get("complex_id")
        unit_no = request.POST.get("unit_no", "").strip()
        block = request.POST.get("block", "").strip()
        area_m2 = request.POST.get("area_m2")
        resident_name = request.POST.get("resident_name", "").strip()
        is_active = request.POST.get("is_active") == "on"

        if not (complex_id and unit_no and area_m2):
            missing_field = (
                "complex_id" if not complex_id else "unit_no" if not unit_no else "area_m2"
            )
            messages.error(
                request,
                "Bina, daire no ve alan alanları zorunludur.",
                extra_tags=f"field-{missing_field}",
            )
        else:
            try:
                updated_apartment = update_apartment(
                    user=request.user,
                    apartment_id=apartment.id,
                    complex_id=int(complex_id),
                    unit_no=unit_no,
                    area_m2=float(area_m2),
                    block=block or None,
                    resident_name=resident_name or None,
                    is_active=is_active,
                )
                record_request(
                    request, action="apartment_update", category=AuditLog.Category.APARTMENT,
                    object_type="Apartment", object_id=updated_apartment.id,
                    object_repr=str(updated_apartment), description="Daire düzenlendi.",
                )
                messages.success(request, f"Daire “{unit_no}” güncellendi.")
                return _redirect_to_user_dashboard(complex_id)
            except ComplexAccessDeniedError as exc:
                messages.error(
                    request,
                    str(exc),
                    extra_tags="field-complex_id",
                )
            except DuplicateApartmentUnitError as exc:
                messages.error(request, str(exc), extra_tags="field-unit_no")
            except IntegrityError:
                # bkz. add_apartment — eşzamanlı istek güvenlik ağı.
                messages.error(
                    request,
                    "Bu daire numarası zaten kullanılmaktadır. Lütfen "
                    "farklı bir daire numarası giriniz.",
                    extra_tags="field-unit_no",
                )
            except (ValueError, InvalidOperation):
                messages.error(
                    request,
                    "Alan (m²) sayısal olmalıdır.",
                    extra_tags="field-area_m2",
                )

    context = {
        "apartment": apartment,
        "complexes": list_accessible_complexes(request.user),
        "resident_name": get_apartment_current_resident_name(apartment),
    }
    return render(request, "dashboard/apartment_edit.html", context)


@user_area_required
def remove_apartment(request, apartment_id):
    apartment = get_object_or_404(
        Apartment.objects.select_related("complex"), pk=apartment_id
    )
    _ensure_apartment_access(request.user, apartment)
    complex_id = apartment.complex_id

    if request.method == "POST":
        unit_no = apartment.unit_no
        hard_deleted = delete_apartment(request.user, apartment_id)
        record_request(
            request, action="apartment_delete", category=AuditLog.Category.APARTMENT,
            object_type="Apartment", object_id=apartment_id,
            object_repr=f"{apartment.complex.name} — {unit_no}",
            description="Daire silindi." if hard_deleted else "Geçmiş kayıtları nedeniyle daire pasif hale getirildi.",
        )
        if hard_deleted:
            messages.success(request, f"Daire “{unit_no}” silindi.")
        else:
            messages.success(
                request,
                f"Daire “{unit_no}” fatura/sayaç geçmişi bulunduğu için "
                "kalıcı olarak silinemedi; bu nedenle pasif hale getirildi.",
            )
    return _redirect_to_user_dashboard(complex_id)


@login_required(login_url="login")
@admin_required
def remove_complex(request, complex_id):
    if request.method == "POST":
        complex_obj = get_object_or_404(
            ApartmentComplex, pk=complex_id, is_deleted=False
        )
        name = complex_obj.name
        delete_complex(complex_id, deleted_by=request.user)
        record_request(
            request,
            action="complex_soft_deleted",
            category=AuditLog.Category.COMPLEX,
            object_type="ApartmentComplex",
            object_id=complex_id,
            object_repr=name,
            description=(
                "Apartman Soft Delete ile silindi. "
                "Bağlı daire, fatura ve sayaç geçmişleri korunmuştur."
            ),
            metadata={"soft_delete": True},
        )
        messages.success(request, f"“{name}” silindi.")
    return redirect("admin_dashboard")


@login_required(login_url="login")
@admin_required
def add_user(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        role = request.POST.get("role", UserProfile.Role.USER)

        if not username or not password:
            messages.error(
                request,
                "Kullanıcı adı ve şifre zorunludur.",
                extra_tags=f"field-{'username' if not username else 'password'}",
            )
        else:
            try:
                validate_password(password)
            except ValidationError as exc:
                messages.error(
                    request,
                    " ".join(exc.messages),
                    extra_tags="field-password",
                )
            else:
                try:
                    created_user = create_user(username=username, password=password, role=role)
                    record_request(
                        request, action="user_create", category=AuditLog.Category.USER,
                        object_type="User", object_id=created_user.id,
                        object_repr=created_user.username, description="Kullanıcı oluşturuldu.",
                    )
                    messages.success(request, f"Kullanıcı “{username}” oluşturuldu.")
                except UsernameAlreadyExistsError as exc:
                    messages.error(
                        request,
                        str(exc),
                        extra_tags="field-username",
                    )
    return redirect("admin_dashboard")


def _password_error(password: str) -> str | None:
    try:
        validate_password(password)
    except ValidationError as exc:
        return " ".join(exc.messages)
    return None


@login_required(login_url="login")
@admin_required
def edit_user(request, user_id):
    target_user = get_object_or_404(
        User.objects.select_related("profile"),
        pk=user_id,
        profile__is_deleted=False,
    )
    target_is_admin = is_admin_user(target_user)
    was_active = target_user.is_active

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        role = request.POST.get("role", UserProfile.Role.USER)
        is_active = True if target_is_admin else request.POST.get("is_active") == "on"
        new_password = request.POST.get("new_password", "")
        complex_ids = [int(v) for v in request.POST.getlist("complex_ids")]
        password_error = _password_error(new_password) if new_password else None

        if not username:
            messages.error(
                request,
                "Kullanıcı adı boş olamaz.",
                extra_tags="field-username",
            )
        elif password_error:
            messages.error(
                request,
                password_error,
                extra_tags="field-new_password",
            )
        else:
            try:
                updated_user = update_user(
                    user_id=target_user.id,
                    username=username,
                    role=role,
                    is_active=is_active,
                    new_password=new_password or None,
                )
                set_complex_access(user_id=target_user.id, complex_ids=complex_ids)
                if was_active != updated_user.is_active:
                    active_state = "aktif" if updated_user.is_active else "pasif"
                    record_request(
                        request,
                        action=(
                            "user_activated"
                            if updated_user.is_active
                            else "user_deactivated"
                        ),
                        category=AuditLog.Category.USER,
                        object_type="User",
                        object_id=updated_user.id,
                        object_repr=updated_user.username,
                        description=f"User {active_state} hale getirildi.",
                    )
                action = "password_change" if new_password else "user_update"
                record_request(
                    request,
                    action=action,
                    category=AuditLog.Category.USER, object_type="User",
                    object_id=target_user.id, object_repr=username,
                    description=(
                        "Kullanıcı düzenlendi ve şifresi değiştirildi."
                        if new_password else "Kullanıcı düzenlendi."
                    ),
                )
                messages.success(request, f"Kullanıcı “{username}” güncellendi.")
                return redirect("admin_dashboard")
            except UsernameAlreadyExistsError as exc:
                messages.error(
                    request,
                    str(exc),
                    extra_tags="field-username",
                )
            except (LastActiveAdminError, AdminDeactivationForbiddenError) as exc:
                record_request(
                    request,
                    action="admin_deactivation_blocked",
                    category=AuditLog.Category.USER,
                    success=False,
                    object_type="User",
                    object_id=target_user.id,
                    object_repr=target_user.username,
                    description="Son aktif admini devre dışı bırakma işlemi engellendi.",
                )
                messages.error(
                    request,
                    str(exc),
                    extra_tags=(
                        "field-role"
                        if isinstance(exc, LastActiveAdminError)
                        else "field-is_active"
                    ),
                )

    context = {
        "target_user": target_user,
        "roles": UserProfile.Role.choices,
        "complexes": list_complexes(),
        "assigned_complex_ids": set(list_complex_access_ids(target_user.id)),
        "target_is_admin": target_is_admin,
    }
    return render(request, "dashboard/user_edit.html", context)


@login_required(login_url="login")
@admin_required
def remove_user(request, user_id):
    if request.method == "POST":
        target_user = get_object_or_404(
            User.objects.select_related("profile"),
            pk=user_id,
            profile__is_deleted=False,
        )
        target_is_admin = is_admin_user(target_user)
        if target_user.id == request.user.id:
            if target_is_admin:
                record_request(
                    request,
                    action="admin_deletion_blocked",
                    category=AuditLog.Category.USER,
                    success=False,
                    object_type="User",
                    object_id=target_user.id,
                    object_repr=target_user.username,
                    description="Yöneticinin kendi hesabını silme işlemi güvenlik nedeniyle engellendi.",
                )
            messages.error(request, "Kendi hesabınızı silemezsiniz.")
        else:
            username = target_user.username
            had_system_history = (
                target_user.billing_runs.exists()
                or target_user.billing_approval_requests.exists()
                or target_user.billing_approval_decisions.exists()
                or target_user.audit_logs.exists()
            )
            try:
                delete_user(user_id, deleted_by=request.user)
                record_request(
                    request,
                    action="admin_deleted" if target_is_admin else "user_soft_deleted",
                    category=AuditLog.Category.USER,
                    object_type="User", object_id=user_id, object_repr=username,
                    description=(
                        "Admin Soft Delete ile silindi."
                        if target_is_admin
                        else "Kullanıcı Soft Delete ile silindi."
                    )
                    + (
                        " İlişkili geçmiş sistem kayıtları korunmuştur."
                        if had_system_history
                        else ""
                    ),
                    metadata={
                        "soft_delete": True,
                        "had_system_history": had_system_history,
                    },
                )
                messages.success(request, f"Kullanıcı “{username}” silindi.")
            except LastAdminDeletionError as exc:
                record_request(
                    request,
                    action="admin_deletion_blocked",
                    category=AuditLog.Category.USER,
                    success=False,
                    object_type="User",
                    object_id=target_user.id,
                    object_repr=target_user.username,
                    description="Son admini silme işlemi güvenlik nedeniyle engellendi.",
                )
                messages.error(request, str(exc))
    return redirect("admin_dashboard")


def _ensure_billing_run_access(user, billing_run: BillingRun) -> None:
    """Bir `BillingRun`'ın ait olduğu apartmana erişim yetkisi yoksa 404
    fırlatır.

    PDF/ZIP indirme uç noktaları da tıpkı `run_billing_or_request_approval`
    gibi apartman bazlı yetkilendirmeye tabidir (bkz. billing/services.py
    `_ensure_complex_access`); burada 403 yerine 404 kullanılması bilinçlidir
    — başka bir kullanıcının faturalandırma kaydının VAR OLDUĞUNU bile ele
    vermemek için.
    """
    accessible_ids = {c.id for c in list_accessible_complexes(user)}
    if billing_run.complex_id not in accessible_ids:
        raise Http404("Bu faturalandırma kaydına erişim yetkiniz yok.")


@login_required(login_url="login")
def download_invoice_pdf(request, run_id, apartment_id):
    """Belirtilen faturalandırma çalıştırması + daire için PDF Gider
    Bildirimini indirir; PDF daha önce üretilmemişse anında üretir."""
    billing_run = get_object_or_404(BillingRun, pk=run_id)
    _ensure_billing_run_access(request.user, billing_run)

    try:
        pdf_path = get_invoice_path_for_apartment(billing_run, apartment_id)
    except ApartmentBillingLine.DoesNotExist as exc:
        raise Http404("Bu daire için bir fatura kaydı bulunamadı.") from exc

    record_request(
        request, action="pdf_create", category=AuditLog.Category.BILLING,
        object_type="ApartmentBillingLine", object_id=apartment_id,
        object_repr=pdf_path.name, description="Tekil fatura PDF'i oluşturuldu veya getirildi.",
        metadata={"billing_run_id": billing_run.id},
    )
    return FileResponse(
        open(pdf_path, "rb"),
        as_attachment=True,
        filename=pdf_path.name,
        content_type="application/pdf",
    )


@login_required(login_url="login")
def download_invoices_zip(request, run_id):
    """Bir faturalandırma çalıştırmasının TÜM daire PDF'lerini (eksik
    olanları tamamlayarak) ve tek bir toplu Excel özetini tek bir ZIP
    dosyası olarak indirir.

    ZIP oluşturma (PDF/Excel üretimi) başarısız olursa — örn. disk dolu,
    font/openpyxl hatası — kullanıcı 500 hata sayfasıyla karşılaşmaz;
    anlaşılır bir Türkçe mesajla kullanıcı paneline geri yönlendirilir.
    """
    billing_run = get_object_or_404(BillingRun, pk=run_id)
    _ensure_billing_run_access(request.user, billing_run)

    try:
        buffer, filename = build_zip_for_run(billing_run)
    except Exception:
        record_request(
            request, action="bulk_pdf_excel_create",
            category=AuditLog.Category.BILLING, success=False,
            object_type="BillingRun", object_id=billing_run.id,
            object_repr=str(billing_run),
            description="Toplu PDF/Excel paketi oluşturulamadı.",
        )
        logger.exception(
            "PDF/Excel ZIP paketi oluşturulamadı (billing_run=%s).", billing_run.id
        )
        messages.error(
            request,
            "Fatura paketi (ZIP) oluşturulurken bir hata oluştu. Lütfen "
            "tekrar deneyin; sorun devam ederse yöneticinizle iletişime geçin.",
        )
        return redirect(f"{reverse('user_dashboard')}?complex_id={billing_run.complex_id}")

    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    record_request(
        request, action="bulk_pdf_excel_create", category=AuditLog.Category.BILLING,
        object_type="BillingRun", object_id=billing_run.id,
        object_repr=filename, description="Toplu PDF/Excel paketi oluşturuldu.",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
