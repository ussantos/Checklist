from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    ActivityLog, CommercialFunnel, CommercialOpportunity,
    CommercialOpportunityFollowUp, CommercialOpportunityStageEvent, FunnelModel,
    FunnelModelField, FunnelStage, FunnelType, Course, Lesson, LessonFeedback, OpportunityOrigin,
    PedagogicalStudent, Position, Room, SchoolHoliday, TimeSlot, UserProfile,
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


@admin.register(FunnelType)
class FunnelTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'active')
    search_fields = ('name', 'code')
    list_filter = ('active',)

    def has_delete_permission(self, request, obj=None):
        return False


class FunnelModelFieldInline(admin.TabularInline):
    model = FunnelModelField
    extra = 0


@admin.register(FunnelStage)
class FunnelStageAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'order', 'active')
    search_fields = ('name', 'code')
    list_filter = ('active',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OpportunityOrigin)
class OpportunityOriginAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'active')
    search_fields = ('name', 'code')
    list_filter = ('active',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FunnelModel)
class FunnelModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'active')
    search_fields = ('name',)
    list_filter = ('active',)
    inlines = [FunnelModelFieldInline]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CommercialFunnel)
class CommercialFunnelAdmin(admin.ModelAdmin):
    list_display = ('name', 'funnel_model', 'active')
    search_fields = ('name', 'funnel_model__name')
    list_filter = ('active', 'funnel_model')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CommercialOpportunity)
class CommercialOpportunityAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'commercial_funnel', 'funnel_type', 'stage', 'origin',
        'owner', 'contact_name', 'contact_phone', 'created_at', 'next_follow_up_date', 'active',
    )
    search_fields = (
        'title', 'contact_name', 'contact_phone', 'commercial_funnel__name',
        'funnel_type__name', 'stage__name', 'origin__name', 'owner__username',
        'owner__first_name', 'owner__last_name',
    )
    list_filter = (
        'active',
        'owner',
        'funnel_type',
        'stage',
        'origin',
        'commercial_funnel',
    )
    readonly_fields = ('created_at',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CommercialOpportunityFollowUp)
class CommercialOpportunityFollowUpAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'opportunity', 'previous_date', 'scheduled_date', 'actor')
    list_filter = ('created_at', 'scheduled_date', 'actor')
    search_fields = ('opportunity__title', 'note', 'actor__username')
    readonly_fields = ('created_at',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CommercialOpportunityStageEvent)
class CommercialOpportunityStageEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'opportunity', 'previous_stage_label', 'new_stage_label', 'actor')
    list_filter = ('created_at', 'previous_stage', 'new_stage', 'actor')
    search_fields = ('opportunity__title', 'previous_stage_label', 'new_stage_label', 'note', 'actor__username')
    readonly_fields = (
        'opportunity', 'previous_stage', 'new_stage', 'previous_stage_label',
        'new_stage_label', 'note', 'actor', 'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('name', 'value', 'kit_quantity', 'active')
    search_fields = ('name',)
    list_filter = ('active',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'capacity', 'active')
    search_fields = ('name',)
    list_filter = ('active',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ('weekday', 'start_time', 'end_time', 'active')
    list_filter = ('weekday', 'active')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SchoolHoliday)
class SchoolHolidayAdmin(admin.ModelAdmin):
    list_display = ('description', 'kind', 'start_date', 'end_date', 'active')
    search_fields = ('description',)
    list_filter = ('kind', 'active')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PedagogicalStudent)
class PedagogicalStudentAdmin(admin.ModelAdmin):
    list_display = ('name', 'enrollment_number', 'responsible_name', 'whatsapp', 'status')
    search_fields = ('name', 'enrollment_number', 'responsible_name', 'whatsapp')
    list_filter = ('status',)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = (
        'date', 'start_time', 'end_time', 'student_name_snapshot', 'lesson_type',
        'trial_kind', 'commercial_opportunity', 'source', 'course', 'room', 'status',
    )
    search_fields = (
        'student_name_snapshot', 'responsible_name_snapshot', 'whatsapp_snapshot',
        'commercial_opportunity__title', 'external_id',
    )
    list_filter = ('lesson_type', 'trial_kind', 'source', 'status', 'course', 'room', 'date')
    readonly_fields = ('created_at', 'updated_at', 'synced_at')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LessonFeedback)
class LessonFeedbackAdmin(admin.ModelAdmin):
    list_display = ('lesson', 'punctuality_score', 'assembly_score', 'participation_score', 'behavior_score', 'general_score', 'updated_at')
    search_fields = ('lesson__student_name_snapshot', 'lesson__course__name', 'general_comment')
    list_filter = ('has_programming', 'lesson__course', 'lesson__date')
    readonly_fields = ('general_score', 'created_at', 'updated_at')

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
