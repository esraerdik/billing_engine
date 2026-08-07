from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Sequence

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from domain.calculator import BillingCalculator
from domain.exceptions import AdminApprovalRequiredError
from domain.history import BillingHistory
from domain.models import Apartment as DomainApartment
from domain.models import BillingPeriod, BillingSummary

from accounts.services import is_admin_user, is_deleted_user
from invoice_pdf.service import generate_invoices_for_run

logger = logging.getLogger(__name__)

from .exceptions import (
    ComplexAccessDeniedError,
    FutureBillingWindowEndError,
    FutureBillingWindowStartError,
    InvalidBillingWindowError,
    InvalidEnergyReadingError,
    SameBillingWindowDatesError,
)
from .models import (
    ApprovalRequest,
    Apartment,
    ApartmentBillingLine,
    ApartmentComplex,
    ApartmentResident,
    BillingRun,
    ComplexAccess,
    MeterDevice,
    MeterReading,
)


def _to_decimal(value: float | Decimal | int) -> Decimal:
    return Decimal(str(value))


def _to_float(value: Decimal) -> float:
    return float(value)


def _window_end_datetime(window_end: date) -> datetime:
    end_of_day = datetime.combine(window_end, time.max)
    if timezone.is_naive(end_of_day):
        return timezone.make_aware(end_of_day)
    return end_of_day


@dataclass(frozen=True)
class ApartmentFormRow:
    apartment_id: int
    unit_no: str
    area_m2: Decimal
    resident_name: str | None
    energy: float | None = None


def get_default_complex() -> ApartmentComplex | None:
    return ApartmentComplex.objects.filter(is_deleted=False).order_by("id").first()


def list_active_apartments(complex_id: int) -> list[ApartmentFormRow]:
    apartments = (
        Apartment.objects.filter(
            complex_id=complex_id,
            complex__is_deleted=False,
            is_active=True,
        )
        .order_by("unit_no")
        .select_related("complex")
    )
    rows: list[ApartmentFormRow] = []
    for apt in apartments:
        resident = (
            ApartmentResident.objects.filter(apartment=apt, ended_at__isnull=True)
            .order_by("-started_at")
            .first()
        )
        rows.append(
            ApartmentFormRow(
                apartment_id=apt.id,
                unit_no=apt.unit_no,
                area_m2=apt.area_m2,
                resident_name=resident.name if resident else None,
            )
        )
    return rows


def list_complexes(*, include_deleted: bool = False) -> list[ApartmentComplex]:
    complexes = ApartmentComplex.objects.all()
    if not include_deleted:
        complexes = complexes.filter(is_deleted=False)
    return list(complexes.order_by("name"))


def list_deleted_complexes() -> list[ApartmentComplex]:
    return list(
        ApartmentComplex.objects.select_related("deleted_by")
        .filter(is_deleted=True)
        .order_by("-deleted_at", "name")
    )


def create_complex(*, name: str, address: str = "") -> ApartmentComplex:
    return ApartmentComplex.objects.create(name=name.strip(), address=address.strip())


def update_complex(*, complex_id: int, name: str, address: str = "") -> ApartmentComplex:
    complex_obj = ApartmentComplex.objects.get(pk=complex_id, is_deleted=False)
    complex_obj.name = name.strip()
    complex_obj.address = address.strip()
    complex_obj.save(update_fields=["name", "address"])
    return complex_obj


@transaction.atomic
def delete_complex(
    complex_id: int, *, deleted_by: AbstractBaseUser | None = None
) -> ApartmentComplex:
    complex_obj = ApartmentComplex.objects.select_for_update().get(
        pk=complex_id, is_deleted=False
    )
    complex_obj.mark_deleted(deleted_by=deleted_by)
    return complex_obj


@transaction.atomic
def restore_complex(complex_id: int) -> ApartmentComplex:
    complex_obj = ApartmentComplex.objects.select_for_update().get(
        pk=complex_id, is_deleted=True
    )
    complex_obj.restore()
    return complex_obj


def list_accessible_complexes(user: AbstractBaseUser) -> list[ApartmentComplex]:
    """Bir kullanıcının erişebileceği apartmanları döndürür.

    Admin rolündeki kullanıcılar TÜM apartmanları görür. "User" rolündeki
    kullanıcılar sadece admin panelinden kendilerine `ComplexAccess`
    üzerinden atanmış apartmanları görür (bkz. `set_complex_access`).
    """
    if is_deleted_user(user) or not getattr(user, "is_active", False):
        return []
    if is_admin_user(user):
        return list_complexes()
    return list(
        ApartmentComplex.objects.filter(
            user_access__user=user, is_deleted=False
        ).order_by("name")
    )


def list_complex_access_ids(user_id: int) -> list[int]:
    return list(
        ComplexAccess.objects.filter(user_id=user_id).values_list(
            "complex_id", flat=True
        )
    )


@transaction.atomic
def set_complex_access(*, user_id: int, complex_ids: list[int]) -> None:
    """Bir kullanıcının erişebileceği apartman kümesini, verilen listeyle
    birebir eşleşecek şekilde günceller (fazlalıkları kaldırır, eksikleri
    ekler).
    """
    complex_ids = set(
        ApartmentComplex.objects.filter(
            pk__in=complex_ids, is_deleted=False
        ).values_list("pk", flat=True)
    )
    ComplexAccess.objects.filter(user_id=user_id).exclude(
        complex_id__in=complex_ids
    ).delete()
    existing_ids = set(
        ComplexAccess.objects.filter(user_id=user_id).values_list(
            "complex_id", flat=True
        )
    )
    for complex_id in complex_ids - existing_ids:
        ComplexAccess.objects.create(user_id=user_id, complex_id=complex_id)


def _ensure_complex_access(user: AbstractBaseUser, complex_id: int) -> None:
    active_complex = ApartmentComplex.objects.filter(
        pk=complex_id, is_deleted=False
    ).first()
    if active_complex is None:
        raise ComplexAccessDeniedError(f"#{complex_id}")
    if is_deleted_user(user) or not getattr(user, "is_active", False):
        raise ComplexAccessDeniedError(active_complex.name)
    if is_admin_user(user):
        return
    has_access = ComplexAccess.objects.filter(
        user=user, complex_id=complex_id, complex__is_deleted=False
    ).exists()
    if not has_access:
        complex_name = (
            ApartmentComplex.objects.filter(pk=complex_id, is_deleted=False)
            .values_list("name", flat=True)
            .first()
            or f"#{complex_id}"
        )
        raise ComplexAccessDeniedError(complex_name)


@dataclass(frozen=True)
class ApartmentListRow:
    apartment_id: int
    unit_no: str
    block: str
    complex_name: str
    area_m2: Decimal
    is_active: bool
    resident_name: str | None


def list_apartments(complex_id: int) -> list[ApartmentListRow]:
    """Belirtilen binadaki (aktif/pasif) TÜM daireleri, daire yönetimi
    (listeleme/düzenleme/silme) için döndürür.

    Daire yönetimi artık user paneline taşındığı için bu liste her zaman
    TEK bir bina ile sınırlıdır — çağıran taraf (view) `complex_id`'nin
    kullanıcının erişebildiği bir bina olduğunu önceden doğrular
    (bkz. `dashboard.views._ensure_apartment_access` ve
    `_ensure_complex_access`).
    """
    apartments = (
        Apartment.objects.filter(
            complex_id=complex_id,
            complex__is_deleted=False,
        )
        .select_related("complex")
        .order_by("unit_no")
    )
    rows: list[ApartmentListRow] = []
    for apt in apartments:
        resident = (
            ApartmentResident.objects.filter(apartment=apt, ended_at__isnull=True)
            .order_by("-started_at")
            .first()
        )
        rows.append(
            ApartmentListRow(
                apartment_id=apt.id,
                unit_no=apt.unit_no,
                block=apt.block,
                complex_name=apt.complex.name,
                area_m2=apt.area_m2,
                is_active=apt.is_active,
                resident_name=resident.name if resident else None,
            )
        )
    return rows


@transaction.atomic
def create_apartment(
    *,
    user: AbstractBaseUser,
    complex_id: int,
    unit_no: str,
    area_m2: float | Decimal,
    block: str | None = None,
    resident_name: str | None = None,
) -> Apartment:
    # Sunucu tarafı yetki kontrolü: kullanıcı yalnızca kendisine atanmış
    # (ComplexAccess) bir binaya daire ekleyebilir. Arayüzden gizlemek
    # yeterli değildir — form/URL manipüle edilse bile burada reddedilir.
    _ensure_complex_access(user, complex_id)
    apartment = Apartment.objects.create(
        complex_id=complex_id,
        unit_no=unit_no.strip(),
        block=block.strip() if block else "",
        area_m2=_to_decimal(area_m2),
    )
    if resident_name and resident_name.strip():
        ApartmentResident.objects.create(
            apartment=apartment,
            name=resident_name.strip(),
            started_at=timezone.now(),
        )
    return apartment


def get_apartment(apartment_id: int) -> Apartment:
    return Apartment.objects.select_related("complex").get(pk=apartment_id)


def get_apartment_current_resident_name(apartment: Apartment) -> str | None:
    resident = (
        ApartmentResident.objects.filter(apartment=apartment, ended_at__isnull=True)
        .order_by("-started_at")
        .first()
    )
    return resident.name if resident else None


@transaction.atomic
def update_apartment(
    *,
    user: AbstractBaseUser,
    apartment_id: int,
    complex_id: int,
    unit_no: str,
    area_m2: float | Decimal,
    block: str | None = None,
    resident_name: str | None = None,
    is_active: bool = True,
) -> Apartment:
    apartment = Apartment.objects.get(pk=apartment_id)
    # Sunucu tarafı yetki kontrolü: hem dairenin MEVCUT binasına hem de
    # (bina değiştiriliyorsa) HEDEF binaya erişim yetkisi olmalıdır —
    # kullanıcı yetkisiz bir binadaki daireyi düzenleyemez ya da bir
    # daireyi yetkisiz bir binaya taşıyamaz.
    _ensure_complex_access(user, apartment.complex_id)
    _ensure_complex_access(user, complex_id)
    apartment.complex_id = complex_id
    apartment.unit_no = unit_no.strip()
    apartment.block = block.strip() if block else ""
    apartment.area_m2 = _to_decimal(area_m2)
    apartment.is_active = is_active
    apartment.save()

    current_resident = (
        ApartmentResident.objects.filter(apartment=apartment, ended_at__isnull=True)
        .order_by("-started_at")
        .first()
    )
    new_name = resident_name.strip() if resident_name else ""
    current_name = current_resident.name if current_resident else ""

    if new_name != current_name:
        # Sakin geçmişi (`ApartmentResident`) hiçbir zaman yerinde
        # güncellenmez — mevcut kayıt kapatılır, gerekirse yeni bir
        # kayıt açılır. Bu, daire değişiminde geçmişin korunması
        # ilkesiyle tutarlıdır (bkz. ApartmentResident modeli).
        if current_resident is not None:
            current_resident.ended_at = timezone.now()
            current_resident.save(update_fields=["ended_at"])
        if new_name:
            ApartmentResident.objects.create(
                apartment=apartment, name=new_name, started_at=timezone.now()
            )

    return apartment


def delete_apartment(user: AbstractBaseUser, apartment_id: int) -> bool:
    """Bir daireyi kalıcı olarak silmeye çalışır.

    Sunucu tarafı yetki kontrolü: kullanıcı yalnızca kendisine atanmış
    binadaki bir daireyi silebilir (bkz. `_ensure_complex_access`).

    `MeterDevice.apartment` ve `ApartmentBillingLine.apartment` ilişkileri
    `PROTECT` olduğundan, bu daireye bağlı en az bir sayaç veya fatura
    satırı (append-only geçmiş) varsa kalıcı silme MÜMKÜN DEĞİLDİR — bu,
    20 yıllık veri saklama gereksiniminin doğal bir sonucudur ve
    değiştirilmez. Ancak bu durumda daire artık sadece bir hata mesajıyla
    olduğu gibi bırakılmaz: `is_active=False` yapılarak aktif daire
    listelerinden ve gelecekteki faturalandırmalardan çıkarılır (bu,
    "Aktif mi?" alanının — bkz. `Apartment.is_active` — doğal bir
    uzantısıdır, YENİ bir alan/mekanizma eklenmez).

    Returns:
        True: Daire kalıcı olarak (satır bazında) silindi.
        False: Kalıcı silme mümkün değildi (ilişkili fatura/sayaç
            geçmişi bulundu); daire bunun yerine pasif hale getirildi.
    """
    apartment = Apartment.objects.get(pk=apartment_id)
    _ensure_complex_access(user, apartment.complex_id)
    try:
        apartment.delete()
        return True
    except ProtectedError:
        if apartment.is_active:
            apartment.is_active = False
            apartment.save(update_fields=["is_active"])
        return False


def _validate_billing_window(window_start: date, window_end: date) -> None:
    """Fatura aralığının KENDİ İÇİNDE tutarlı olduğunu doğrular.

    Kurallar: `window_start` gelecekte bir tarih olamaz; `window_start`,
    `window_end`'den sonra olamaz; ikisi birbirine eşit olamaz; `window_end`
    gelecekte bir tarih olamaz. Tarih aralığının geçmiş faturalandırmalarla
    ÇAKIŞIP çakışmadığı burada
    KONTROL EDİLMEZ ve bir çakışma artık asla sessizce/sert biçimde
    reddedilmez — çakışma, yeniden faturalandırma (admin onay) akışını
    TETİKLER (bkz. `_overlapping_runs_exist` ve
    `run_billing_or_request_approval`). Bu ayrım iş kuralının doğrudan
    bir sonucudur: "daha önce faturalandırılmış herhangi bir tarihle
    çakışma varsa, kullanıcı doğrudan hesaplayamaz; bir onay talebi
    oluşturulur."

    Bu kontrol `run_billing`/`run_billing_or_request_approval`'ın en
    başında, authorizer/hesaplama hiç çalışmadan önce yapılır — tıpkı
    `BillingCalculator._validate`'in "önce genel/global koşullar"
    prensibiyle aynı mantık.
    """
    today = timezone.localdate()
    if window_start > today:
        raise FutureBillingWindowStartError(window_start, today)
    if window_start > window_end:
        raise InvalidBillingWindowError(window_start, window_end)
    if window_start == window_end:
        raise SameBillingWindowDatesError(window_start)
    if window_end > today:
        raise FutureBillingWindowEndError(window_end, today)


def _overlapping_runs_exist(
    complex_id: int, window_start: date, window_end: date
) -> bool:
    """Bu aralığın, aynı bina için daha önce KALICI hâle gelmiş (bir
    `BillingRun` satırı olan) herhangi bir faturalandırma penceresiyle
    gün bazında çakışıp çakışmadığını döndürür.

    Standart aralık kesişim koşulu kullanılır:
        existing.start <= new.end AND existing.end >= new.start

    Bu koşul, iş kuralında sayılan tüm çakışma biçimlerini kapsar:
      - yeni aralık eskinin İÇİNDE kalıyorsa,
      - eski aralık yeninin İÇİNDE kalıyorsa,
      - kenarlar (başlangıç/bitiş) kesişiyorsa,
      - iki aralık arasında tek bir ORTAK GÜN bile varsa
        (örn. eski [1-10], yeni [10-20] → 10. gün ortaktır).
    Birebir aynı aralık da doğal olarak bir çakışmadır; bu kontrolde
    ona AYRICALIK TANINMAZ — her çakışma, farkı olmaksızın admin onay
    akışına yönlendirilir.
    """
    return BillingRun.objects.filter(
        complex_id=complex_id,
        window_start_date__lte=window_end,
        window_end_date__gte=window_start,
    ).exists()


def _approved_request_for_retry(
    *,
    complex_id: int,
    user: AbstractBaseUser,
    window_start: date,
    window_end: date,
) -> ApprovalRequest | None:
    """Bu kullanıcı/aralık için onaylanmış ve henüz tüketilmemiş talebi bulur."""
    return (
        ApprovalRequest.objects.filter(
            complex_id=complex_id,
            requested_by=user,
            window_start_date=window_start,
            window_end_date=window_end,
            status=ApprovalRequest.Status.APPROVED,
            billing_run__isnull=True,
        )
        .order_by("decided_at", "requested_at")
        .first()
    )


def _active_meter_device(apartment: Apartment) -> MeterDevice | None:
    return (
        MeterDevice.objects.filter(apartment=apartment, is_active=True)
        .order_by("-installed_at")
        .first()
    )


def _previous_end_reading(apartment: Apartment) -> MeterReading | None:
    previous_line = (
        ApartmentBillingLine.objects.filter(
            apartment=apartment,
            end_reading__isnull=False,
        )
        .select_related("end_reading", "billing_run")
        .order_by("-billing_run__recorded_at")
        .first()
    )
    return previous_line.end_reading if previous_line else None


def _earliest_reading(device: MeterDevice) -> MeterReading | None:
    return device.readings.order_by("read_at").first()


def _latest_reading_on_or_before(
    device: MeterDevice, window_end: date
) -> MeterReading | None:
    cutoff = _window_end_datetime(window_end)
    return device.readings.filter(read_at__lte=cutoff).order_by("-read_at").first()


def derive_consumption(
    apartment: Apartment,
    window_end: date,
) -> tuple[MeterReading | None, MeterReading | None, Decimal | None]:
    device = _active_meter_device(apartment)
    if device is None:
        return None, None, None

    start_reading = _previous_end_reading(apartment)
    if start_reading is None:
        start_reading = _earliest_reading(device)

    end_reading = _latest_reading_on_or_before(device, window_end)
    if start_reading is None or end_reading is None:
        return start_reading, end_reading, None

    consumed = end_reading.raw_value - start_reading.raw_value
    return start_reading, end_reading, consumed


@dataclass(frozen=True)
class _ApartmentEnergyMeta:
    """Bir dairenin bu çalıştırmadaki enerji endeks/okuma bilgisi.

    `start_reading`/`end_reading`/`consumed`, (ileride) Modbus'tan otomatik
    türetilen kalorimetre okumalarını temsil eder (bkz. `derive_consumption`).
    `manual_start`/`manual_end`, kullanıcının kullanıcı panelinden GİRDİĞİ
    kümülatif "İlk Enerji"/"Son Enerji" endeksleridir. İkisi karşılıklı
    dışlayıcı değildir ama pratikte bir daire için ya biri ya diğeri
    doludur. `_persist_billing_run`, PDF'in "Sayaç Bilgileri" bölümünde
    gösterilecek `start_energy_value`/`end_energy_value`'yu bu ikisinden
    HANGİSİ mevcutsa ondan türetir — bu sayede manuel giriş ile ileride
    gerçek Modbus okumaları tamamen aynı alanlar üzerinden PDF'e akar.
    """

    start_reading: MeterReading | None
    end_reading: MeterReading | None
    consumed: Decimal | None
    manual_start: Decimal | None = None
    manual_end: Decimal | None = None


def _build_domain_apartments(
    complex_id: int,
    window_end: date,
    manual_energy: dict[int, tuple[float, float]] | None = None,
) -> tuple[list[DomainApartment], dict[int, _ApartmentEnergyMeta]]:
    """Domain hesaplamasına girecek `Apartment` listesini ve her dairenin
    enerji kökenini (Modbus okuması mı, manuel "İlk/Son Enerji" girişi mi)
    kurar.

    `manual_energy`, artık tek bir tüketim değeri DEĞİL, kullanıcı
    panelinden girilen `(ilk_enerji, son_enerji)` çiftidir — kümülatif
    sayaç mantığıyla (ve ileride gerçek Modbus okumalarıyla) tutarlı
    olması için tüketim burada `son - ilk` olarak türetilir; PDF veya
    başka hiçbir katman bu farkı yeniden hesaplamaz.
    """
    apartments = Apartment.objects.filter(
        complex_id=complex_id, is_active=True
    ).order_by("unit_no")
    domain_apartments: list[DomainApartment] = []
    energy_meta: dict[int, _ApartmentEnergyMeta] = {}

    for apt in apartments:
        start_r, end_r, consumed = derive_consumption(apt, window_end)

        manual_start_dec: Decimal | None = None
        manual_end_dec: Decimal | None = None

        if manual_energy is not None and apt.id in manual_energy:
            manual_start_raw, manual_end_raw = manual_energy[apt.id]
            if manual_end_raw < manual_start_raw:
                raise InvalidEnergyReadingError(
                    unit_no=apt.unit_no,
                    start_value=manual_start_raw,
                    end_value=manual_end_raw,
                )
            manual_start_dec = _to_decimal(manual_start_raw)
            manual_end_dec = _to_decimal(manual_end_raw)
            energy = manual_end_raw - manual_start_raw
        elif consumed is not None:
            energy = _to_float(consumed)
        else:
            energy = 0.0

        energy_meta[apt.id] = _ApartmentEnergyMeta(
            start_reading=start_r,
            end_reading=end_r,
            consumed=consumed,
            manual_start=manual_start_dec,
            manual_end=manual_end_dec,
        )

        domain_apartments.append(
            DomainApartment(
                id=apt.id,
                area=_to_float(apt.area_m2),
                energy=energy,
            )
        )

    return domain_apartments, energy_meta


def _persist_billing_run(
    *,
    complex_obj: ApartmentComplex,
    user: AbstractBaseUser,
    period: BillingPeriod,
    window_start: date,
    window_end: date,
    summary: BillingSummary,
    energy_meta: dict[int, _ApartmentEnergyMeta],
) -> BillingRun:
    billing_run = BillingRun.objects.create(
        complex=complex_obj,
        period_year=period.year,
        period_month=period.month,
        window_start_date=window_start,
        window_end_date=window_end,
        total_bill=_to_decimal(summary.total_bill),
        total_fixed_amount=_to_decimal(summary.total_fixed_amount),
        total_consumption_amount=_to_decimal(summary.total_consumption_amount),
        total_area=_to_decimal(summary.total_area),
        total_energy=_to_decimal(summary.total_energy),
        run_by=user,
    )

    apartment_map = {
        apt.id: apt
        for apt in Apartment.objects.filter(
            id__in=[r.apartment_id for r in summary.results]
        )
    }

    for result in summary.results:
        apt = apartment_map[result.apartment_id]
        meta = energy_meta.get(result.apartment_id)
        start_r = meta.start_reading if meta else None
        end_r = meta.end_reading if meta else None
        consumed = meta.consumed if meta else None
        energy_consumed = (
            consumed if consumed is not None else _to_decimal(result.energy)
        )

        # PDF'in "Sayaç Bilgileri" bölümünde gösterilecek İlk/Son Enerji
        # endeksleri: önce manuel giriş, yoksa Modbus okuması, ikisi de
        # yoksa `None` ("—" olarak gösterilir — bkz. invoice_pdf).
        if meta is not None and meta.manual_start is not None and meta.manual_end is not None:
            start_energy_value = meta.manual_start
            end_energy_value = meta.manual_end
        elif start_r is not None and end_r is not None:
            start_energy_value = start_r.raw_value
            end_energy_value = end_r.raw_value
        else:
            start_energy_value = None
            end_energy_value = None

        ApartmentBillingLine.objects.create(
            billing_run=billing_run,
            apartment=apt,
            start_reading=start_r,
            end_reading=end_r,
            energy_consumed=energy_consumed,
            start_energy_value=start_energy_value,
            end_energy_value=end_energy_value,
            area_ratio=_to_decimal(result.area_ratio),
            energy_ratio=_to_decimal(result.energy_ratio),
            fixed_share=_to_decimal(result.fixed_share),
            consumption_share=_to_decimal(result.consumption_share),
            total_payable=_to_decimal(result.total_payable),
            status=ApartmentBillingLine.Status.NORMAL,
        )

    return billing_run


def _create_approval_request(
    *,
    complex_obj: ApartmentComplex,
    period: BillingPeriod,
    window_start: date,
    window_end: date,
    user: AbstractBaseUser,
) -> ApprovalRequest:
    """Her yeniden hesaplama denemesi için yeni, append-only talep oluşturur.

    Bilinçli olarak `get_or_create`, `update_or_create` veya mevcut PENDING
    kayıt sorgusu kullanılmaz. Aynı aralık için eski talep pending,
    onaylanmış ya da reddedilmiş olsa da her yeni deneme ayrı satırdır.
    """
    return ApprovalRequest.objects.create(
        complex=complex_obj,
        period_year=period.year,
        period_month=period.month,
        window_start_date=window_start,
        window_end_date=window_end,
        requested_by=user,
    )


@transaction.atomic
def run_billing(
    *,
    complex_id: int,
    user: AbstractBaseUser,
    window_start: date,
    window_end: date,
    total_bill: float,
    manual_energy: dict[int, tuple[float, float]] | None = None,
    approval_request: ApprovalRequest | None = None,
) -> tuple[BillingRun, BillingSummary]:
    _ensure_complex_access(user, complex_id)
    _validate_billing_window(window_start, window_end)

    # Aynı binaya gelen eşzamanlı ilk/yeniden hesaplama denemelerinin
    # ikisinin birden "ilk çalıştırma" görmesini engeller. PostgreSQL'de
    # satır kilidi transaction sonuna kadar tutulur; SQLite'ta güvenli
    # biçimde normal sorgu gibi davranır.
    complex_obj = ApartmentComplex.objects.select_for_update().get(pk=complex_id)
    # `BillingPeriod` (domain katmanı) hâlâ ay/yıl bazlıdır — bu değerler
    # artık kullanıcıdan istenmiyor, `window_start`'ın ait olduğu takvim
    # ayından otomatik türetiliyor. Bu, YALNIZCA `BillingRunAuthorizer`nın
    # "ayda N ücretsiz çalıştırma" politikası için iç muhasebe amaçlıdır;
    # gerçek fatura penceresi (`window_start`/`window_end`) tamamen
    # bağımsız kalır (bkz. domain/models.py'ye hiç dokunulmaması kararı).
    period_year = window_start.year
    period_month = window_start.month
    period = BillingPeriod(year=period_year, month=period_month)

    # Bu aralık, geçmiş bir faturalandırmayla çakışıyorsa (kısmi çakışma
    # dâhil — bkz. `_overlapping_runs_exist`), doğrudan hesaplama YAPILMAZ;
    # yalnızca geçerli, onaylanmış ve HENÜZ TÜKETİLMEMİŞ bir onay talebi
    # varsa çalışır. Bu, `run_billing`'in doğrudan (wrapper'sız) çağrıldığı
    # durumları da korur.
    needs_approval = _overlapping_runs_exist(complex_id, window_start, window_end)
    if needs_approval:
        if approval_request is not None:
            approval_request = ApprovalRequest.objects.select_for_update().get(
                pk=approval_request.pk
            )
        valid_approval = (
            approval_request is not None
            and approval_request.complex_id == complex_id
            and approval_request.requested_by_id == user.pk
            and approval_request.window_start_date == window_start
            and approval_request.window_end_date == window_end
            and approval_request.status == ApprovalRequest.Status.APPROVED
            and approval_request.billing_run_id is None
        )
        if not valid_approval:
            raise AdminApprovalRequiredError(period)

    calculator = BillingCalculator()
    history = BillingHistory()

    domain_apartments, energy_meta = _build_domain_apartments(
        complex_id, window_end, manual_energy
    )

    summary = calculator.calculate(total_bill=total_bill, apartments=domain_apartments)
    history.record(period, summary)

    billing_run = _persist_billing_run(
        complex_obj=complex_obj,
        user=user,
        period=period,
        window_start=window_start,
        window_end=window_end,
        summary=summary,
        energy_meta=energy_meta,
    )

    if approval_request is not None:
        approval_request.billing_run = billing_run
        approval_request.save(update_fields=["billing_run"])

    # PDF Gider Bildirimi üretimi, faturalandırma iş mantığından TAMAMEN
    # BAĞIMSIZDIR (bkz. invoice_pdf paketi) — bu yüzden burada bilinçli
    # olarak geniş bir `except` ile sarılmıştır. `run_billing` zaten
    # persist edildiği (transaction'ın geri kalanı başarıyla tamamlandığı)
    # için, PDF üretiminde çıkabilecek herhangi bir hata (örn. disk dolu,
    # font sorunu) faturalandırma sonucunu ASLA geçersiz kılmamalı/geri
    # aldırmamalıdır — kullanıcı PDF'i daha sonra panelden tekrar
    # indirmeyi deneyebilir.
    try:
        generate_invoices_for_run(billing_run)
    except Exception:
        logger.exception(
            "PDF Gider Bildirimi üretimi başarısız oldu (billing_run=%s); "
            "faturalandırma sonucu bundan etkilenmedi.",
            billing_run.id,
        )

    return billing_run, summary


def run_billing_or_request_approval(
    *,
    complex_id: int,
    user: AbstractBaseUser,
    window_start: date,
    window_end: date,
    total_bill: float,
    manual_energy: dict[int, tuple[float, float]] | None = None,
) -> tuple[BillingRun, BillingSummary]:
    _ensure_complex_access(user, complex_id)
    _validate_billing_window(window_start, window_end)

    complex_obj = ApartmentComplex.objects.get(pk=complex_id)
    period_year = window_start.year
    period_month = window_start.month
    period = BillingPeriod(year=period_year, month=period_month)

    approval_request = None
    if _overlapping_runs_exist(complex_id, window_start, window_end):
        approval_request = _approved_request_for_retry(
            complex_id=complex_id,
            user=user,
            window_start=window_start,
            window_end=window_end,
        )
        if approval_request is None:
            _create_approval_request(
                complex_obj=complex_obj,
                period=period,
                window_start=window_start,
                window_end=window_end,
                user=user,
            )
            raise AdminApprovalRequiredError(period)

    try:
        return run_billing(
            complex_id=complex_id,
            user=user,
            window_start=window_start,
            window_end=window_end,
            total_bill=total_bill,
            manual_energy=manual_energy,
            approval_request=approval_request,
        )
    except AdminApprovalRequiredError:
        # Onay, iki eşzamanlı istek arasında tam bu sırada başka bir
        # başarılı yeniden hesaplama tarafından tüketilmiş olabilir.
        # Bu deneme de kaybolmamalı; ayrı bir talep olarak saklanır.
        _create_approval_request(
            complex_obj=complex_obj,
            period=period,
            window_start=window_start,
            window_end=window_end,
            user=user,
        )
        raise


def list_pending_approval_requests() -> list[ApprovalRequest]:
    return list(
        ApprovalRequest.objects.filter(
            status=ApprovalRequest.Status.PENDING,
            complex__is_deleted=False,
        )
        .select_related("complex", "requested_by")
        .order_by("requested_at")
    )


@transaction.atomic
def approve_request(request_id: int, admin_user: AbstractBaseUser) -> None:
    approval = ApprovalRequest.objects.select_for_update().get(
        pk=request_id,
        complex__is_deleted=False,
    )
    if approval.status != ApprovalRequest.Status.PENDING:
        return

    approval.status = ApprovalRequest.Status.APPROVED
    approval.decided_by = admin_user
    approval.decided_at = timezone.now()
    approval.save(update_fields=["status", "decided_by", "decided_at"])


@transaction.atomic
def deny_request(request_id: int, admin_user: AbstractBaseUser) -> None:
    approval = ApprovalRequest.objects.select_for_update().get(
        pk=request_id,
        complex__is_deleted=False,
    )
    if approval.status != ApprovalRequest.Status.PENDING:
        return

    approval.status = ApprovalRequest.Status.DENIED
    approval.decided_by = admin_user
    approval.decided_at = timezone.now()
    approval.save(update_fields=["status", "decided_by", "decided_at"])
