from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import (
    ActivityLog, ChecklistOccurrence, DailyNote, EmployeeAbsence, EvidenceAttachment,
    MetricRecord, MetricType, Position, TaskTemplate, UserProfile,
)


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


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'system_role', 'position', 'active', 'must_change_password', 'user')
    list_filter = ('system_role', 'position', 'active', 'must_change_password')
    search_fields = ('display_name', 'user__username', 'position__name')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmployeeAbsence)
class EmployeeAbsenceAdmin(admin.ModelAdmin):
    list_display = ('profile', 'absence_type', 'start_date', 'end_date', 'active', 'created_by')
    list_filter = ('absence_type', 'active', 'start_date')
    search_fields = ('profile__display_name', 'profile__user__username', 'reason')
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'start_date'

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ('position', 'day_of_week', 'start_time', 'end_time', 'title', 'frequency', 'active')
    list_filter = ('position', 'frequency', 'day_of_week', 'category', 'active')
    search_fields = ('title', 'description', 'expected_result', 'evidence_required', 'proof_location', 'notes')
    ordering = ('position', 'day_of_week', 'order')

    def has_delete_permission(self, request, obj=None):
        return False


class EvidenceAttachmentInline(admin.TabularInline):
    model = EvidenceAttachment
    extra = 0
    readonly_fields = ('uploaded_at',)


@admin.register(ChecklistOccurrence)
class ChecklistOccurrenceAdmin(admin.ModelAdmin):
    list_display = ('date', 'position', 'template', 'status', 'executor_full_name', 'updated_by', 'updated_at')
    list_filter = ('date', 'position', 'status')
    search_fields = ('template__title', 'executor_full_name', 'evidence_text', 'blocked_reason')
    inlines = [EvidenceAttachmentInline]
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    date_hierarchy = 'date'


@admin.register(DailyNote)
class DailyNoteAdmin(admin.ModelAdmin):
    list_display = ('date', 'position', 'executor_full_name', 'updated_at')
    list_filter = ('position', 'date')
    search_fields = ('notes', 'executor_full_name')
    date_hierarchy = 'date'


@admin.register(MetricType)
class MetricTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'position', 'monthly_target', 'unit', 'active')
    list_filter = ('position', 'active')
    search_fields = ('name', 'code')


@admin.register(MetricRecord)
class MetricRecordAdmin(admin.ModelAdmin):
    list_display = ('date', 'position', 'metric', 'value', 'executor_full_name', 'created_by')
    list_filter = ('position', 'metric', 'date')
    search_fields = ('notes', 'metric__name', 'executor_full_name')
    date_hierarchy = 'date'


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'position', 'action', 'object_type', 'object_id')
    list_filter = ('action', 'position', 'created_at')
    search_fields = ('details', 'action', 'actor__username')
    readonly_fields = ('created_at',)


@admin.register(EvidenceAttachment)
class EvidenceAttachmentAdmin(admin.ModelAdmin):
    list_display = ('occurrence', 'original_name', 'uploaded_by', 'uploaded_at')
    list_filter = ('uploaded_at', 'uploaded_by')
    search_fields = ('original_name', 'occurrence__template__title', 'occurrence__executor_full_name')
    readonly_fields = ('uploaded_at',)
