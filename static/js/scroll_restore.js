/*
 * scroll_restore.js
 * ------------------
 * Bu proje form gönderimlerinde (daire/bina/kullanıcı ekleme, hesaplama,
 * onay/red vb.) klasik POST-Redirect-GET akışını kullanır; her gönderimde
 * tam sayfa yenilenir ve tarayıcı varsayılan olarak sayfanın en üstüne
 * döner. Bu, uzun listelerde (çok sayıda daire/kullanıcı) veri girişini
 * yorucu hale getirir.
 *
 * Bu script, herhangi bir backend/iş mantığı değişikliği YAPMADAN, salt
 * istemci tarafında şu davranışı sağlar: sayfadan ayrılmadan hemen önceki
 * kaydırma (scroll) konumu tarayıcının `sessionStorage`'ına kaydedilir;
 * aynı adres tekrar yüklendiğinde (form gönderiminin döndüğü sayfa da
 * genelde aynı adrestir) bu konum geri yüklenir. Böylece kullanıcı yeni
 * bir daire eklediğinde veya bir kaydı güncellediğinde sayfa en başa
 * dönmez, kaldığı yerde kalır.
 */

(function () {
    "use strict";

    var STORAGE_KEY = "billingEngine:scrollPos:" + window.location.pathname;

    window.addEventListener("beforeunload", function () {
        sessionStorage.setItem(STORAGE_KEY, String(window.scrollY));
    });

    document.addEventListener("DOMContentLoaded", function () {
        var saved = sessionStorage.getItem(STORAGE_KEY);
        if (saved === null) {
            return;
        }
        sessionStorage.removeItem(STORAGE_KEY);

        var targetY = parseInt(saved, 10);
        if (Number.isNaN(targetY)) {
            return;
        }

        // Tarayıcının kendi scroll restorasyonuyla çakışmaması için bir
        // sonraki "paint" turunda uyguluyoruz.
        window.requestAnimationFrame(function () {
            window.scrollTo(0, targetY);
        });
    });
})();
