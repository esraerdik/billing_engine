from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.shortcuts import redirect, render

from .services import is_admin_user


def _dashboard_redirect_name(user) -> str:
    """Giriş yapan kullanıcının rolüne göre yönlendirileceği ekranı belirler."""
    return "admin_dashboard" if is_admin_user(user) else "user_dashboard"


def login_view(request):
    error = None

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            django_login(request, user)
            return redirect(_dashboard_redirect_name(user))

        error = "Kullanıcı adı veya şifre hatalı."

    return render(
        request,
        "accounts/login.html",
        {
            "error": error,
        },
    )


def logout_view(request):
    django_logout(request)
    return redirect("login")


def csrf_failure_view(request, reason=""):
    """Django'nun varsayılan teknik CSRF hata sayfası yerine kullanıcıyı
    dostane bir mesajla giriş ekranına geri gönderir.

    Bu durum genellikle şu senaryolarda ortaya çıkar: sayfa uzun süre açık
    kalmış, oturum/CSRF çerezi bir başka sekmede yapılan giriş/çıkış
    sırasında yenilenmiş, ya da tarayıcı "geri" tuşuyla eski bir forma
    dönülmüş olabilir. Kullanıcıdan beklenen tek şey formu tekrar
    doldurup göndermesidir; bu yüzden teknik detay göstermek yerine
    doğrudan giriş sayfasına yönlendiriyoruz.
    """
    messages.error(
        request,
        "Oturumunuzun süresi dolmuş olabilir. Lütfen tekrar giriş yapıp "
        "işlemi yeniden deneyin.",
    )
    return redirect("login")
