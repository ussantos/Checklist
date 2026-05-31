from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import (
    ActivityLog, ActivitySuggestion, ChecklistOccurrence,
    ChecklistOccurrenceStatusEvent, DailyNote, EmployeeAbsence,
    EvidenceAttachment, MetricRecord, MetricType, Position, TaskTemplate,
    UserProfile,
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
    list_display = ('position', 'day_of_week', 'start_time', 'end_time', 'title', 'frequency', 'requires_evidence', 'active')
    list_filter = ('position', 'frequency', 'day_of_week', 'category', 'requires_evidence', 'active')
    search_fields = ('title', 'description', 'expected_result', 'evidence_required', 'proof_location', 'notes')
    ordering = ('position', 'day_of_week', 'order')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ActivitySuggestion)
class ActivitySuggestionAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'request_type', 'status', 'position', 'requested_by', 'target_template', 'created_template')
    list_filter = ('status', 'request_type', 'position', 'created_at')
    search_fields = ('title', 'target_template__title', 'requested_by__username', 'position__name', 'justification')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at')

    def has_delete_permission(self, request, obj=None):
        return False


class EvidenceAttachmentInline(admin.TabularInline):
    model = EvidenceAttachment
    extra = 0
    readonly_fields = ('uploaded_at',)


class StatusEventInline(admin.TabularInline):
    model = ChecklistOccurrenceStatusEvent
    extra = 0
    can_delete = False
    readonly_fields = ('previous_status', 'new_status', 'changed_by', 'changed_at', 'created_at')
    fields = ('previous_status', 'new_status', 'changed_by', 'changed_at', 'created_at')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ChecklistOccurrence)
class ChecklistOccurrenceAdmin(admin.ModelAdmin):
    list_display = ('date', 'position', 'template', 'status', 'executor_full_name', 'updated_by', 'updated_at')
    list_filter = ('date', 'position', 'status')
    search_fields = ('template__title', 'executor_full_name', 'evidence_text', 'blocked_reason')
    inlines = [EvidenceAttachmentInline, StatusEventInline]
    readonly_fields = ('created_at', 'updated_at', 'completed_at')
    date_hierarchy = 'date'

    def save_model(self, request, obj, form, change):
        previous_status = ''
        if change and obj.pk:
            previous_status = ChecklistOccurrence.objects.get(pk=obj.pk).status
        super().save_model(request, obj, form, change)
        if not change or previous_status != obj.status:
            ChecklistOccurrenceStatusEvent.objects.create(
                occurrence=obj,
                previous_status=previous_status,
                new_status=obj.status,
                changed_by=request.user,
            )


@admin.register(DailyNote)
class DailyNoteAdmin(admin.ModelAdmin):
    list_display = ('date', 'position', 'executor_full_name', 'updated_at')
    list_filter = ('position', 'date')
    search_fields = ('notes', 'executor_full_name')
    date_hierarchy = 'date'


@admin.register(MetricType)
class MetricTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'area', 'frequency', 'position', 'activity', 'monthly_target', 'unit', 'active')
    list_filter = ('position', 'frequency', 'area', 'active')
    search_fields = ('name', 'code', 'area', 'activity__title')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MetricRecord)
class MetricRecordAdmin(admin.ModelAdmin):
    list_display = ('date', 'position', 'metric', 'value', 'executor_full_name', 'created_by')
    list_filter = ('position', 'metric', 'date')
    search_fields = ('notes', 'metric__name', 'executor_full_name')
    date_hierarchy = 'date'


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'position', 'action', 'object_type', 'object_id', 'object_label')
    list_filter = ('action', 'object_type', 'position', 'created_at')
    search_fields = ('details', 'object_label', 'action', 'actor__username', 'object_type', 'object_id')
    readonly_fields = ('created_at',)


@admin.register(EvidenceAttachment)
class EvidenceAttachmentAdmin(admin.ModelAdmin):
    list_display = ('occurrence', 'original_name', 'uploaded_by', 'uploaded_at')
    list_filter = ('uploaded_at', 'uploaded_by')
    search_fields = ('original_name', 'occurrence__template__title', 'occurrence__executor_full_name')
    readonly_fields = ('uploaded_at',)


@admin.register(ChecklistOccurrenceStatusEvent)
class ChecklistOccurrenceStatusEventAdmin(admin.ModelAdmin):
    list_display = ('changed_at', 'occurrence', 'previous_status', 'new_status', 'changed_by')
    list_filter = ('new_status', 'changed_at', 'changed_by')
    search_fields = ('occurrence__template__title', 'occurrence__position__name', 'changed_by__username')
    readonly_fields = ('occurrence', 'previous_status', 'new_status', 'changed_by', 'changed_at', 'created_at')
    date_hierarchy = 'changed_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
