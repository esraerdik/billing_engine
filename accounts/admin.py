from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    fk_name = "user"
    can_delete = False
    verbose_name_plural = "Rol"
    readonly_fields = ("is_deleted", "deleted_at", "deleted_by")


class UserAdmin(DjangoUserAdmin):
    inlines = [UserProfileInline]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(profile__is_deleted=False)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_inline_instances(self, request, obj=None):
        # Yeni kullanıcı eklenirken (obj henüz yok) inline'ı gösterme:
        # `UserProfile`, `accounts.signals.create_user_profile` tarafından
        # kullanıcı kaydedildiği anda otomatik oluşturuluyor. Inline'ı
        # "add" formunda da göstermek, aynı OneToOne kayıt için hem
        # sinyalin hem de inline formset'in ayrı ayrı satır oluşturmaya
        # çalışmasına (IntegrityError) yol açar. Bu yüzden inline sadece
        # "change" formunda (obj var) gösterilir — rol ataması/değişimi
        # kullanıcı oluşturulduktan HEMEN SONRA, düzenleme ekranından yapılır.
        if not obj:
            return []
        return super().get_inline_instances(request, obj)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
