from django.urls import path

from . import views

urlpatterns = [
    path("user/", views.user_dashboard, name="user_dashboard"),
    path("admin/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/deleted-users/", views.deleted_users, name="deleted_users"),
    path(
        "admin/deleted-users/<int:user_id>/restore/",
        views.restore_deleted_user,
        name="restore_deleted_user",
    ),
    path(
        "admin/deleted-complexes/",
        views.deleted_complexes,
        name="deleted_complexes",
    ),
    path(
        "admin/deleted-complexes/<int:complex_id>/restore/",
        views.restore_deleted_complex,
        name="restore_deleted_complex",
    ),
    path("admin/audit-logs/", views.audit_logs, name="audit_logs"),
    path(
        "admin/meter-reading-history/",
        views.meter_reading_history,
        name="meter_reading_history",
    ),
    path("approve/<int:request_id>/", views.approve, name="approve"),
    path("reject/<int:request_id>/", views.reject, name="reject"),
    path("admin/complexes/add/", views.add_complex, name="add_complex"),
    path(
        "admin/complexes/<int:complex_id>/edit/",
        views.edit_complex,
        name="edit_complex",
    ),
    path(
        "admin/complexes/<int:complex_id>/delete/",
        views.remove_complex,
        name="delete_complex",
    ),
    # Daire yönetimi user paneline taşındı (bkz. dashboard.views.user_area_required).
    path("user/apartments/add/", views.add_apartment, name="add_apartment"),
    path(
        "user/apartments/<int:apartment_id>/edit/",
        views.edit_apartment,
        name="edit_apartment",
    ),
    path(
        "user/apartments/<int:apartment_id>/delete/",
        views.remove_apartment,
        name="delete_apartment",
    ),
    path("admin/users/add/", views.add_user, name="add_user"),
    path("admin/users/<int:user_id>/edit/", views.edit_user, name="edit_user"),
    path(
        "admin/users/<int:user_id>/delete/",
        views.remove_user,
        name="delete_user",
    ),
    path(
        "invoices/run/<int:run_id>/apartment/<int:apartment_id>/pdf/",
        views.download_invoice_pdf,
        name="download_invoice_pdf",
    ),
    path(
        "invoices/run/<int:run_id>/zip/",
        views.download_invoices_zip,
        name="download_invoices_zip",
    ),
]
