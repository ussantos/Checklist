from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import ActivityLog, FunnelType, Position, UserProfile


User = get_user_model()

try:
    admin.site.unregister(User)
except NotRegistered:
    pass


@admin.register(User)
class ChecklistUserAdmin(DjangoUserAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'active')
    search_fields = ('name', 'code')
    list_filter = ('active',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FunnelType)
class FunnelTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'active')
    search_fields = ('name', 'code')
    list_filter = ('active',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'system_role', 'position', 'active', 'must_change_password', 'user')
    list_filter = ('system_role', 'position', 'active', 'must_change_password')
    search_fields = ('display_name', 'user__username', 'position__name')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'position', 'action', 'object_type', 'object_id', 'object_label')
    list_filter = ('action', 'object_type', 'position', 'created_at')
    search_fields = ('details', 'object_label', 'action', 'actor__username', 'object_type', 'object_id')
    readonly_fields = ('created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
