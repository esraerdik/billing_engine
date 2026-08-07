/*
 * Django Messages toast'ları, tekrar kullanılabilir onay modalı ve
 * istemci tarafı form hata geri bildirimi.
 */
(function () {
    "use strict";

    var toastContainer;
    var confirmationModal;
    var pendingConfirmation = null;
    var previouslyFocused = null;
    var invalidBatchFirstField = null;

    function normalizeLevel(level) {
        return ["success", "info", "warning", "error"].indexOf(level) >= 0
            ? level
            : "info";
    }

    function dismissToast(toast) {
        if (!toast || toast.classList.contains("is-leaving")) {
            return;
        }
        window.clearTimeout(toast._dismissTimer);
        toast.classList.add("is-leaving");
        window.setTimeout(function () {
            toast.remove();
        }, 240);
    }

    function activateToast(toast) {
        var level = normalizeLevel(toast.dataset.toastLevel);
        var timeout = level === "error" || level === "warning" ? 6500 : 4500;
        toast.dataset.toastLevel = level;
        window.requestAnimationFrame(function () {
            toast.classList.add("is-visible");
        });
        toast._dismissTimer = window.setTimeout(function () {
            dismissToast(toast);
        }, timeout);
    }

    function showToast(message, level) {
        if (!toastContainer || !message) {
            return null;
        }
        level = normalizeLevel(level);
        var toast = document.createElement("div");
        toast.className = "app-toast app-toast--" + level;
        toast.dataset.appToast = "";
        toast.dataset.toastLevel = level;
        toast.setAttribute("role", level === "error" ? "alert" : "status");

        var icon = document.createElement("span");
        icon.className = "app-toast__icon";
        icon.setAttribute("aria-hidden", "true");

        var text = document.createElement("span");
        text.className = "app-toast__message";
        text.textContent = message;

        var close = document.createElement("button");
        close.type = "button";
        close.className = "app-toast__close";
        close.dataset.toastClose = "";
        close.setAttribute("aria-label", "Bildirimi kapat");
        close.textContent = "×";

        toast.append(icon, text, close);
        toastContainer.appendChild(toast);
        activateToast(toast);
        return toast;
    }

    function validationMessageFor(field) {
        if (field.validity.valueMissing) {
            return "Bu alan zorunludur.";
        }
        if (field.validity.typeMismatch || field.validity.badInput) {
            return "Lütfen geçerli bir değer girin.";
        }
        if (field.validity.rangeUnderflow) {
            return "Girilen değer izin verilen minimum değerden küçük.";
        }
        if (field.validity.rangeOverflow) {
            return "Girilen değer izin verilen maksimum değerden büyük.";
        }
        if (field.validity.stepMismatch) {
            return "Lütfen geçerli bir sayı girin.";
        }
        return field.validationMessage || "Lütfen bu alanı kontrol edin.";
    }

    function showFieldError(field, message) {
        if (!field) {
            return;
        }
        field.classList.add("is-invalid");
        field.setAttribute("aria-invalid", "true");

        var error = field.nextElementSibling;
        if (!error || !error.classList.contains("field-error-message")) {
            error = document.createElement("div");
            error.className = "field-error-message";
            error.setAttribute("role", "alert");
            field.insertAdjacentElement("afterend", error);
        }
        error.textContent = message || "Lütfen bu alanı kontrol edin.";
    }

    function clearFieldError(field) {
        field.classList.remove("is-invalid");
        field.removeAttribute("aria-invalid");
        var error = field.nextElementSibling;
        if (error && error.classList.contains("field-error-message")) {
            error.remove();
        }
    }

    function focusField(field) {
        if (!field) {
            return;
        }
        field.scrollIntoView({ behavior: "smooth", block: "center" });
        window.setTimeout(function () {
            try {
                field.focus({ preventScroll: true });
            } catch (error) {
                field.focus();
            }
        }, 280);
    }

    function closeConfirmation() {
        if (!confirmationModal) {
            return;
        }
        confirmationModal.classList.remove("is-open", "is-success");
        confirmationModal.hidden = true;
        document.body.classList.remove("has-app-modal");
        pendingConfirmation = null;
        if (previouslyFocused) {
            previouslyFocused.focus();
        }
    }

    function openConfirmation(options) {
        var title = confirmationModal.querySelector("[data-confirm-title]");
        var message = confirmationModal.querySelector("[data-confirm-message]");
        var accept = confirmationModal.querySelector("[data-confirm-accept]");

        pendingConfirmation = options.onConfirm;
        previouslyFocused = document.activeElement;
        title.textContent = options.title || "Silme Onayı";
        message.textContent =
            options.message || "Bu kaydı silmek istediğinize emin misiniz?";
        accept.textContent = options.label || "Evet, Sil";
        confirmationModal.classList.toggle(
            "is-success",
            options.variant === "success"
        );
        confirmationModal.hidden = false;
        document.body.classList.add("has-app-modal");
        window.requestAnimationFrame(function () {
            confirmationModal.classList.add("is-open");
            accept.focus();
        });
    }

    function fieldFromToastTags(toast) {
        var tags = (toast.dataset.toastTags || "").split(/\s+/);
        var fieldTag = tags.find(function (tag) {
            return tag.indexOf("field-") === 0;
        });
        if (!fieldTag) {
            return null;
        }
        var candidates = document.getElementsByName(fieldTag.slice(6));
        return candidates.length ? candidates[0] : null;
    }

    function initializeUiFeedback() {
        toastContainer = document.querySelector("[data-toast-container]");
        confirmationModal = document.querySelector("[data-confirm-modal]");

        var firstServerErrorField = null;
        document.querySelectorAll("[data-app-toast]").forEach(function (toast) {
            activateToast(toast);
            if (toast.dataset.toastLevel === "error") {
                var field = fieldFromToastTags(toast);
                if (field) {
                    showFieldError(
                        field,
                        toast.querySelector(".app-toast__message").textContent
                    );
                    firstServerErrorField = firstServerErrorField || field;
                }
            }
        });

        document.querySelectorAll("[data-toast-message]").forEach(function (source) {
            showToast(
                source.dataset.toastMessage,
                source.dataset.toastLevel || "info"
            );
            if (source.dataset.toastField) {
                var candidates = document.getElementsByName(
                    source.dataset.toastField
                );
                if (candidates.length) {
                    showFieldError(candidates[0], source.dataset.toastMessage);
                    firstServerErrorField =
                        firstServerErrorField || candidates[0];
                }
            }
        });

        if (firstServerErrorField) {
            focusField(firstServerErrorField);
        }
    }

    document.addEventListener("click", function (event) {
        var closeButton = event.target.closest("[data-toast-close]");
        if (closeButton) {
            dismissToast(closeButton.closest("[data-app-toast]"));
            return;
        }

        if (event.target.closest("[data-confirm-cancel]")) {
            closeConfirmation();
            return;
        }

        if (event.target.closest("[data-confirm-accept]")) {
            var action = pendingConfirmation;
            closeConfirmation();
            if (action) {
                action();
            }
            return;
        }

        var confirmationLink = event.target.closest("[data-confirm-url]");
        if (confirmationLink) {
            event.preventDefault();
            openConfirmation({
                title: confirmationLink.dataset.confirmTitle,
                message: confirmationLink.dataset.confirmMessage,
                label: confirmationLink.dataset.confirmLabel,
                variant: confirmationLink.dataset.confirmVariant,
                onConfirm: function () {
                    window.location.assign(confirmationLink.href);
                },
            });
        }
    });

    document.addEventListener(
        "submit",
        function (event) {
            var form = event.target;
            if (!form.matches("[data-confirm-form]")) {
                return;
            }
            if (form.dataset.confirmed === "true") {
                delete form.dataset.confirmed;
                return;
            }

            event.preventDefault();
            var submitter = event.submitter;
            openConfirmation({
                title: form.dataset.confirmTitle,
                message: form.dataset.confirmMessage,
                label: form.dataset.confirmLabel,
                variant: form.dataset.confirmVariant,
                onConfirm: function () {
                    form.dataset.confirmed = "true";
                    if (form.requestSubmit) {
                        form.requestSubmit(submitter);
                    } else {
                        form.submit();
                    }
                },
            });
        },
        true
    );

    document.addEventListener(
        "invalid",
        function (event) {
            var field = event.target;
            if (!field.matches("input, select, textarea")) {
                return;
            }
            showFieldError(field, validationMessageFor(field));
            if (!invalidBatchFirstField) {
                invalidBatchFirstField = field;
                window.setTimeout(function () {
                    showToast("Lütfen işaretli alanları kontrol edin.", "error");
                    focusField(invalidBatchFirstField);
                    invalidBatchFirstField = null;
                }, 0);
            }
        },
        true
    );

    document.addEventListener("input", function (event) {
        var field = event.target;
        if (
            field.matches("input, select, textarea") &&
            field.classList.contains("is-invalid") &&
            field.checkValidity()
        ) {
            clearFieldError(field);
        }
    });

    document.addEventListener("keydown", function (event) {
        if (
            event.key === "Escape" &&
            confirmationModal &&
            !confirmationModal.hidden
        ) {
            closeConfirmation();
        }
    });

    window.AppUI = {
        showToast: showToast,
        showFieldError: showFieldError,
        clearFieldError: clearFieldError,
        openConfirmation: openConfirmation,
    };

    // Script base.html'in sonunda, ortak markup'tan sonra yüklenir.
    initializeUiFeedback();
})();
