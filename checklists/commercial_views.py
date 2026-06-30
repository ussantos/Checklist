from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .audit import changed_values, log_activity, snapshot_instance
from .forms import (
    CommercialFunnelForm, CommercialOpportunityForm, FunnelModelFieldFormSet,
    FunnelModelForm, FunnelStageForm, FunnelTypeForm, OpportunityOriginForm,
    add_months, is_lost_stage,
)
from .models import (
    CommercialFunnel, CommercialOpportunity, CommercialOpportunityFollowUp,
    Course,
    CommercialOpportunityStageEvent, FunnelModel, FunnelModelField, FunnelStage,
    FunnelType, Lesson, OpportunityOrigin, Room, SchoolHoliday, TimeSlot,
)
from .services import (
    _post_sale_funnel_components, get_user_position, is_admin_user,
    next_commercial_opportunity_code,
)


COMMERCIAL_POSITION_CODE = 'atendente-comercial'


FUNNEL_TYPE_AUDIT_FIELDS = ['name', 'code', 'active']
FUNNEL_STAGE_AUDIT_FIELDS = ['name', 'code', 'description', 'order', 'active']
OPPORTUNITY_ORIGIN_AUDIT_FIELDS = ['name', 'code', 'description', 'active']
FUNNEL_MODEL_AUDIT_FIELDS = ['name', 'active']
COMMERCIAL_FUNNEL_AUDIT_FIELDS = ['name', 'funnel_model', 'active']
COMMERCIAL_OPPORTUNITY_AUDIT_FIELDS = [
    'title', 'commercial_funnel', 'funnel_type', 'stage', 'origin', 'contact_name', 'contact_phone',
    'interest_course', 'interest_type', 'value', 'owner', 'next_follow_up_date', 'field_values', 'notes', 'active',
    'automation_key', 'created_at',
]


def _admin_check(user):
    return user.is_authenticated and is_admin_user(user)


def _commercial_access_check(user):
    if not user.is_authenticated:
        return False
    if is_admin_user(user):
        return True
    position = get_user_position(user)
    return bool(position and position.code == COMMERCIAL_POSITION_CODE)


def _is_commercial_operator(user):
    position = get_user_position(user)
    return bool(position and position.code == COMMERCIAL_POSITION_CODE and not is_admin_user(user))


def _is_commercial_admin_context(user):
    return is_admin_user(user)


def _scope_commercial_opportunities(queryset, user):
    if is_admin_user(user):
        return queryset
    return queryset.filter(owner=user)


def _funnel_model_snapshot(funnel_model):
    data = snapshot_instance(funnel_model, FUNNEL_MODEL_AUDIT_FIELDS)
    data['fields'] = [
        {
            'name': field.name,
            'field_type': field.field_type,
            'required': field.required,
            'options': field.options,
            'order': field.order,
        }
        for field in funnel_model.fields.all().order_by('order', 'id')
    ]
    return data


def _commercial_opportunity_queryset():
    return CommercialOpportunity.objects.select_related(
        'commercial_funnel',
        'commercial_funnel__funnel_model',
        'funnel_type',
        'stage',
        'origin',
        'interest_course',
        'owner',
    ).prefetch_related('commercial_funnel__funnel_model__fields')


def _commercial_opportunity_snapshot(opportunity):
    return snapshot_instance(opportunity, COMMERCIAL_OPPORTUNITY_AUDIT_FIELDS)


def _opportunity_custom_values(opportunity):
    values = opportunity.field_values or {}
    display_values = []
    for field in opportunity.commercial_funnel.funnel_model.fields.all().order_by('order', 'id'):
        raw_value = values.get(str(field.pk), '')
        if raw_value in (None, ''):
            continue
        if field.field_type == FunnelModelField.TYPE_BOOLEAN:
            value = 'Sim' if raw_value else 'Não'
        else:
            value = raw_value
        display_values.append({'label': field.name, 'value': value})
    return display_values


def _group_opportunities_by_funnel_stage(opportunities, *, max_per_stage=None):
    groups = []
    funnel_index = {}
    stage_index_by_funnel = {}
    for opportunity in opportunities:
        funnel_key = opportunity.commercial_funnel_id or 0
        if funnel_key not in funnel_index:
            group = {
                'funnel': opportunity.commercial_funnel,
                'total': 0,
                'stages': [],
            }
            funnel_index[funnel_key] = group
            stage_index_by_funnel[funnel_key] = {}
            groups.append(group)

        group = funnel_index[funnel_key]
        group['total'] += 1
        stage_key = opportunity.stage_id or 0
        if stage_key not in stage_index_by_funnel[funnel_key]:
            stage_group = {
                'stage': opportunity.stage,
                'total': 0,
                'opportunities': [],
            }
            stage_index_by_funnel[funnel_key][stage_key] = stage_group
            group['stages'].append(stage_group)

        stage_group = stage_index_by_funnel[funnel_key][stage_key]
        stage_group['total'] += 1
        if max_per_stage is None or len(stage_group['opportunities']) < max_per_stage:
            stage_group['opportunities'].append(opportunity)
    return groups


def _kanban_columns_for_funnel(opportunities):
    stages = list(FunnelStage.objects.filter(active=True).order_by('order', 'name'))
    stage_ids = {stage.id for stage in stages}
    extra_stage_ids = {opportunity.stage_id for opportunity in opportunities if opportunity.stage_id and opportunity.stage_id not in stage_ids}
    if extra_stage_ids:
        stages.extend(FunnelStage.objects.filter(pk__in=extra_stage_ids).order_by('order', 'name'))

    columns = []
    index = {}
    for stage in stages:
        column = {
            'stage': stage,
            'opportunities': [],
        }
        columns.append(column)
        index[stage.id] = column

    without_stage = {
        'stage': None,
        'opportunities': [],
    }
    for opportunity in opportunities:
        if opportunity.stage_id and opportunity.stage_id in index:
            index[opportunity.stage_id]['opportunities'].append(opportunity)
        else:
            without_stage['opportunities'].append(opportunity)

    if without_stage['opportunities']:
        columns.append(without_stage)
    return columns


def _record_follow_up_event(*, opportunity, actor, previous_date=None, note=''):
    return CommercialOpportunityFollowUp.objects.create(
        opportunity=opportunity,
        previous_date=previous_date,
        scheduled_date=opportunity.next_follow_up_date,
        note=(note or '').strip(),
        actor=actor,
    )


def _stage_label(stage):
    return str(stage) if stage else ''


def _record_stage_event(*, opportunity, actor, previous_stage=None, note=''):
    return CommercialOpportunityStageEvent.objects.create(
        opportunity=opportunity,
        previous_stage=previous_stage,
        new_stage=opportunity.stage,
        previous_stage_label=_stage_label(previous_stage),
        new_stage_label=_stage_label(opportunity.stage),
        note=(note or '').strip(),
        actor=actor,
    )


def _stage_by_code_or_text(*, code='', text=''):
    if code:
        stage = FunnelStage.objects.filter(code=code).first()
        if stage:
            return stage
    text = slugify(text or code)
    for stage in FunnelStage.objects.all().order_by('order', 'name'):
        candidate = slugify(f'{stage.code} {stage.name}')
        if text and text in candidate:
            return stage
    return None


def _trial_lesson_stage():
    return _stage_by_code_or_text(code='3-aula-experimental', text='aula experimental')


def _is_enrollment_stage(stage):
    if not stage:
        return False
    enrollment_stage = _stage_by_code_or_text(code='5-matricula', text='matricula')
    if enrollment_stage:
        return stage.pk == enrollment_stage.pk
    stage_text = slugify(f'{stage.code} {stage.name}')
    return 'matricula' in stage_text and '5' in stage_text


def _interested_funnel_type():
    return (
        FunnelType.objects.filter(code='interessados').first()
        or FunnelType.objects.filter(name__iexact='Interessados').first()
    )


def _interested_funnel():
    funnel_type = _interested_funnel_type()
    queryset = CommercialFunnel.objects.select_related('funnel_model').order_by('-active', 'name')
    if funnel_type:
        return (
            queryset.filter(name__iexact=funnel_type.name).first()
            or queryset.filter(funnel_model__funnel_type=funnel_type).first()
        )
    return queryset.filter(name__iexact='Interessados').first()


def _apply_opportunity_business_rules(opportunity, *, form):
    if form.trial_lesson_payload:
        trial_stage = _trial_lesson_stage()
        if trial_stage:
            opportunity.stage = trial_stage

    if is_lost_stage(opportunity.stage):
        interested_funnel = _interested_funnel()
        if interested_funnel:
            opportunity.commercial_funnel = interested_funnel
            opportunity.funnel_type = (
                interested_funnel.funnel_model.funnel_type
                or _interested_funnel_type()
                or opportunity.funnel_type
            )
        else:
            opportunity.funnel_type = _interested_funnel_type() or opportunity.funnel_type
        opportunity.next_follow_up_date = add_months(timezone.localdate(), 3)
        opportunity.active = False
    elif _is_enrollment_stage(opportunity.stage):
        post_sale_funnel_type, _post_sale_stage, _post_sale_origin, post_sale_funnel = _post_sale_funnel_components()
        opportunity.commercial_funnel = post_sale_funnel
        opportunity.funnel_type = post_sale_funnel_type
    elif not opportunity.funnel_type_id:
        opportunity.funnel_type = (
            getattr(opportunity.commercial_funnel.funnel_model, 'funnel_type', None)
            or FunnelType.objects.filter(code=slugify(opportunity.commercial_funnel.name)).first()
            or FunnelType.objects.filter(name__iexact=opportunity.commercial_funnel.name).first()
        )
    return opportunity


def _parse_week_start(value):
    today = timezone.localdate()
    if value:
        try:
            target = datetime.fromisoformat(value).date()
        except ValueError:
            target = today
    else:
        target = today
    return target - timedelta(days=target.weekday())


def _slot_value(target_date, slot, room):
    return f'{target_date.isoformat()}|{slot.start_time:%H:%M}|{slot.end_time:%H:%M}|{room.pk}'


def _slot_label(target_date, slot, room):
    return f'{target_date:%d/%m} {slot.start_time:%H:%M}-{slot.end_time:%H:%M} · {room.name}'


def _slot_start(slot):
    return slot['start_time'] if isinstance(slot, dict) else slot.start_time


def _slot_end(slot):
    return slot['end_time'] if isinstance(slot, dict) else slot.end_time


def _overlaps_slot(lesson, target_date, slot):
    return (
        lesson.date == target_date
        and lesson.start_time < _slot_end(slot)
        and lesson.end_time > _slot_start(slot)
    )


def _trial_slot_block_reasons(*, lessons, target_date, slot, room, course=None):
    overlapping = [
        lesson
        for lesson in lessons
        if _overlaps_slot(lesson, target_date, slot)
    ]
    reasons = []
    room_occupancy = sum(1 for lesson in overlapping if lesson.room_id == room.id)
    if room_occupancy >= room.capacity:
        reasons.append(f'sala cheia ({room_occupancy}/{room.capacity})')

    if course:
        course_occupancy = sum(1 for lesson in overlapping if lesson.course_id == course.id)
        if course_occupancy >= course.kit_quantity:
            reasons.append(
                f'kits insuficientes para {course.name} '
                f'({course_occupancy}/{course.kit_quantity} em uso)'
            )
    return reasons


def _trial_slot_base_context(week_start):
    today = timezone.localdate()
    now_time = timezone.localtime().time()
    rooms = list(Room.objects.filter(active=True).order_by('name'))
    time_slots = list(TimeSlot.objects.filter(active=True).order_by('weekday', 'start_time', 'end_time'))
    if not rooms or not time_slots:
        return [], []

    week_end = week_start + timedelta(days=5)
    holidays = list(
        SchoolHoliday.objects.filter(active=True, start_date__lte=week_end, end_date__gte=week_start)
    )
    lessons = list(
        Lesson.objects.filter(
            date__range=(week_start, week_end),
            status__in=Lesson.OCCUPYING_STATUSES,
        ).select_related('room')
    )

    slots = []
    for day_offset in range(6):
        target_date = week_start + timedelta(days=day_offset)
        if target_date < today:
            continue
        if any(holiday.start_date <= target_date <= holiday.end_date for holiday in holidays):
            continue
        for slot in [item for item in time_slots if item.weekday == target_date.weekday()]:
            if target_date == today and slot.start_time <= now_time:
                continue
            for room in rooms:
                slots.append({
                    'value': _slot_value(target_date, slot, room),
                    'label': _slot_label(target_date, slot, room),
                    'day_label': target_date.strftime('%A'),
                    'date': target_date,
                    'start_time': slot.start_time,
                    'end_time': slot.end_time,
                    'room': room,
                })
    return slots, lessons


def _available_trial_slots(week_start, course=None):
    slots, lessons = _trial_slot_base_context(week_start)
    return [
        slot
        for slot in slots
        if not _trial_slot_block_reasons(
            lessons=lessons,
            target_date=slot['date'],
            slot=slot,
            room=slot['room'],
            course=course,
        )
    ]


def _trial_calendar_slots(week_start):
    slots, lessons = _trial_slot_base_context(week_start)
    courses = list(Course.objects.filter(active=True).order_by('name'))
    for slot in slots:
        room_reasons = _trial_slot_block_reasons(
            lessons=lessons,
            target_date=slot['date'],
            slot=slot,
            room=slot['room'],
        )
        slot['room_available'] = not room_reasons
        slot['room_block_reason'] = '; '.join(room_reasons)
        slot['available_course_ids'] = []
        slot['blocked_courses'] = []
        for course in courses:
            reasons = _trial_slot_block_reasons(
                lessons=lessons,
                target_date=slot['date'],
                slot=slot,
                room=slot['room'],
                course=course,
            )
            if reasons:
                slot['blocked_courses'].append({
                    'course': course,
                    'reason': '; '.join(reasons),
                })
            else:
                slot['available_course_ids'].append(str(course.pk))
        slot['available_course_ids_csv'] = ','.join(slot['available_course_ids'])
    return slots


def _trial_lesson_course_from_request(request):
    if request.method != 'POST':
        return None
    course_id = request.POST.get('trial_lesson_course')
    try:
        return Course.objects.filter(pk=int(course_id)).first() if course_id else None
    except (TypeError, ValueError):
        return None


def _group_slots_by_day(slots):
    grouped = []
    current_key = None
    for slot in slots:
        key = slot['date']
        if key != current_key:
            grouped.append({'date': key, 'slots': []})
            current_key = key
        grouped[-1]['slots'].append(slot)
    return grouped


def _build_trial_lesson_from_form(*, opportunity, form, actor):
    payload = form.trial_lesson_payload
    if not payload:
        return None
    lesson = Lesson(
        lesson_type=Lesson.TYPE_TRIAL,
        trial_kind=payload['trial_kind'],
        commercial_opportunity=opportunity,
        student_name_snapshot=payload.get('student_name') or opportunity.contact_name,
        responsible_name_snapshot=opportunity.contact_name,
        whatsapp_snapshot=opportunity.contact_phone,
        course=payload['course'],
        room=payload['room'],
        date=payload['date'],
        start_time=payload['start_time'],
        end_time=payload['end_time'],
        status=Lesson.STATUS_NOT_GIVEN,
        notes=payload['notes'],
        created_by=actor,
    )
    lesson.full_clean()
    return lesson


def _log_trial_lesson_created(*, actor, lesson):
    log_activity(
        actor=actor,
        obj=lesson,
        action='Aula Experimental ou Play criada pela oportunidade',
        object_label=str(lesson),
        details=(
            f'Aula: {lesson}; oportunidade: {lesson.commercial_opportunity}; '
            f'tipo: {lesson.get_trial_kind_display()}'
        ),
        new_values=snapshot_instance(lesson, [
            'lesson_type', 'trial_kind', 'commercial_opportunity', 'student_name_snapshot',
            'responsible_name_snapshot', 'whatsapp_snapshot', 'course', 'room', 'date',
            'start_time', 'end_time', 'status', 'notes', 'created_by',
        ]),
    )


def _confirm_delete(request, *, title, object_label, warning, cancel_url):
    return render(request, 'checklists/commercial_confirm_delete.html', {
        'title': title,
        'object_label': object_label,
        'warning': warning,
        'cancel_url': cancel_url,
        'is_admin': True,
    })


def _commercial_redirect_name(user):
    return 'commercial_opportunities' if is_admin_user(user) else 'commercial_dashboard'


def _commercial_form_context(request, *, form, title, submit_label, opportunity=None, week_start=None, slots=None, extra=None):
    slots = slots or []
    selected_slot = form['trial_lesson_slot'].value()
    context = {
        'form': form,
        'title': title,
        'submit_label': submit_label,
        'opportunity': opportunity,
        'is_admin': _is_commercial_admin_context(request.user),
        'is_commercial_operator': _is_commercial_operator(request.user),
        'week_start': week_start,
        'previous_week': week_start - timedelta(days=7) if week_start else None,
        'next_week': week_start + timedelta(days=7) if week_start else None,
        'available_trial_slots': slots,
        'available_trial_slots_by_day': _group_slots_by_day(slots),
        'selected_trial_lesson_slot': selected_slot,
        'selected_stage_requires_trial_lesson': form.selected_stage_requires_trial_lesson,
        'creation_date': opportunity.created_at.date() if opportunity else timezone.localdate(),
        'trial_lesson_stage_id': getattr(_trial_lesson_stage(), 'id', ''),
        'lost_stage_id': getattr(_stage_by_code_or_text(code='5-perdido', text='perdido'), 'id', ''),
        'interested_funnel_id': getattr(_interested_funnel(), 'id', ''),
        'lost_follow_up_date': add_months(timezone.localdate(), 3),
    }
    if extra:
        context.update(extra)
    return context


@user_passes_test(_commercial_access_check)
def commercial_dashboard(request):
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    stale_threshold = timezone.now() - timedelta(days=3)
    opportunities = _scope_commercial_opportunities(
        _commercial_opportunity_queryset().filter(active=True),
        request.user,
    )

    follow_up_today = opportunities.filter(next_follow_up_date=today).order_by('next_follow_up_date', 'title')
    follow_up_tomorrow = opportunities.filter(next_follow_up_date=tomorrow).order_by('next_follow_up_date', 'title')
    overdue = opportunities.filter(next_follow_up_date__lt=today).order_by('next_follow_up_date', 'title')
    stale = opportunities.filter(updated_at__lt=stale_threshold).order_by('updated_at', 'title')
    critical = stale.filter(next_follow_up_date__lt=today).order_by('next_follow_up_date', 'updated_at')

    dashboard_opportunities = list(
        opportunities.order_by(
            'commercial_funnel__name',
            'stage__order',
            'stage__name',
            'next_follow_up_date',
            'title',
        )
    )
    opportunity_funnel_groups = _group_opportunities_by_funnel_stage(dashboard_opportunities, max_per_stage=4)

    return render(request, 'checklists/commercial_dashboard.html', {
        'today': today,
        'tomorrow': tomorrow,
        'follow_up_today_count': follow_up_today.count(),
        'follow_up_tomorrow_count': follow_up_tomorrow.count(),
        'overdue_count': overdue.count(),
        'critical_count': critical.count(),
        'stale_count': stale.count(),
        'opportunity_funnel_groups': opportunity_funnel_groups,
        'follow_up_today': follow_up_today[:8],
        'follow_up_tomorrow': follow_up_tomorrow[:8],
        'overdue': overdue[:10],
        'critical_opportunities': critical[:10],
        'stale_opportunities': stale[:10],
        'is_admin': _is_commercial_admin_context(request.user),
        'is_commercial_operator': _is_commercial_operator(request.user),
    })


def _parse_week_reference(value):
    if not value:
        return timezone.localdate()
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return timezone.localdate()


@user_passes_test(_commercial_access_check)
def commercial_follow_up_agenda(request):
    week_reference = _parse_week_reference(request.GET.get('semana'))
    week_start = week_reference - timedelta(days=week_reference.weekday())
    week_end = week_start + timedelta(days=6)
    today = timezone.localdate()

    opportunities = list(
        _scope_commercial_opportunities(
            _commercial_opportunity_queryset().filter(
                active=True,
                next_follow_up_date__gte=week_start,
                next_follow_up_date__lte=week_end,
            ),
            request.user,
        ).order_by(
            'next_follow_up_date',
            'commercial_funnel__name',
            'stage__order',
            'stage__name',
            'contact_name',
            'title',
        )
    )

    opportunities_by_day = {}
    for opportunity in opportunities:
        if opportunity.next_follow_up_date < today:
            opportunity.follow_up_state = 'is-overdue'
            opportunity.follow_up_state_label = 'Atrasado'
        elif opportunity.next_follow_up_date == today:
            opportunity.follow_up_state = 'is-today'
            opportunity.follow_up_state_label = 'Hoje'
        else:
            opportunity.follow_up_state = ''
            opportunity.follow_up_state_label = opportunity.next_follow_up_date.strftime('%d/%m')
        opportunities_by_day.setdefault(opportunity.next_follow_up_date, []).append(opportunity)

    week_days = []
    current_day = week_start
    while current_day <= week_end:
        day_opportunities = opportunities_by_day.get(current_day, [])
        week_days.append({
            'date': current_day,
            'opportunities': day_opportunities,
            'count': len(day_opportunities),
            'is_today': current_day == today,
            'is_weekend': current_day.weekday() >= 5,
        })
        current_day += timedelta(days=1)

    return render(request, 'checklists/commercial_follow_up_agenda.html', {
        'week_start': week_start,
        'week_end': week_end,
        'previous_week': week_start - timedelta(days=7),
        'next_week': week_start + timedelta(days=7),
        'current_week': today - timedelta(days=today.weekday()),
        'week_days': week_days,
        'opportunity_count': len(opportunities),
        'today': today,
        'is_admin': _is_commercial_admin_context(request.user),
        'is_commercial_operator': _is_commercial_operator(request.user),
    })


@user_passes_test(_commercial_access_check)
def commercial_funnel_board(request):
    funnels = list(CommercialFunnel.objects.filter(active=True).select_related('funnel_model').order_by('name'))
    selected_funnel_id = request.GET.get('funil', '')
    selected_funnel = None
    if selected_funnel_id and selected_funnel_id.isdigit():
        selected_funnel = CommercialFunnel.objects.filter(pk=selected_funnel_id).select_related('funnel_model').first()
    if not selected_funnel and funnels:
        selected_funnel = next(
            (funnel for funnel in funnels if funnel.name.casefold() == 'qualificados'),
            funnels[0],
        )
        selected_funnel_id = str(selected_funnel.id)
    elif selected_funnel:
        selected_funnel_id = str(selected_funnel.id)
        if selected_funnel not in funnels:
            funnels.append(selected_funnel)
            funnels.sort(key=lambda item: item.name.casefold())
    else:
        selected_funnel_id = ''

    opportunities = _scope_commercial_opportunities(
        _commercial_opportunity_queryset().filter(active=True),
        request.user,
    )
    if selected_funnel:
        opportunities = opportunities.filter(commercial_funnel=selected_funnel)
    opportunities = list(opportunities.order_by('stage__order', 'stage__name', 'next_follow_up_date', 'title'))
    columns = _kanban_columns_for_funnel(opportunities) if selected_funnel else []
    today = timezone.localdate()
    for opportunity in opportunities:
        if opportunity.next_follow_up_date < today:
            opportunity.follow_up_state = 'overdue'
            opportunity.follow_up_state_label = 'Atrasado'
        elif opportunity.next_follow_up_date == today:
            opportunity.follow_up_state = 'today'
            opportunity.follow_up_state_label = 'Hoje'
        else:
            opportunity.follow_up_state = 'future'
            opportunity.follow_up_state_label = opportunity.next_follow_up_date.strftime('%d/%m')

    return render(request, 'checklists/commercial_funnel_board.html', {
        'funnels': funnels,
        'selected_funnel': selected_funnel,
        'selected_funnel_id': selected_funnel_id,
        'columns': columns,
        'opportunity_count': len(opportunities),
        'today': today,
        'is_admin': _is_commercial_admin_context(request.user),
        'is_commercial_operator': _is_commercial_operator(request.user),
    })


@user_passes_test(_admin_check)
def funnel_types_list(request):
    status = request.GET.get('status', 'ativos')
    funnel_types = FunnelType.objects.all().order_by('-active', 'name')
    if status == 'inativos':
        funnel_types = funnel_types.filter(active=False)
    elif status != 'todos':
        status = 'ativos'
        funnel_types = funnel_types.filter(active=True)

    funnel_types = list(funnel_types)
    for funnel_type in funnel_types:
        funnel_type.can_delete_from_ui = funnel_type.can_be_deleted()

    return render(request, 'checklists/funnel_types_list.html', {
        'funnel_types': funnel_types,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def funnel_type_create(request):
    if request.method == 'POST':
        form = FunnelTypeForm(request.POST)
        if form.is_valid():
            funnel_type = form.save()
            log_activity(
                actor=request.user,
                obj=funnel_type,
                action='Tipo de funil criado',
                object_label=funnel_type.name,
                details=f'Tipo de funil: {funnel_type.name}; código: {funnel_type.code}; ativo: {funnel_type.active}',
                new_values=snapshot_instance(funnel_type, FUNNEL_TYPE_AUDIT_FIELDS),
            )
            messages.success(request, 'Tipo de funil criado.')
            return redirect('commercial_funnel_types')
    else:
        form = FunnelTypeForm()

    return render(request, 'checklists/funnel_type_form.html', {
        'form': form,
        'title': 'Inserir tipo de funil',
        'submit_label': 'Inserir tipo de funil',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def funnel_type_edit(request, funnel_type_id):
    funnel_type = get_object_or_404(FunnelType, pk=funnel_type_id)
    previous_active = funnel_type.active
    previous_values_full = snapshot_instance(funnel_type, FUNNEL_TYPE_AUDIT_FIELDS)
    if request.method == 'POST':
        form = FunnelTypeForm(request.POST, instance=funnel_type)
        if form.is_valid():
            funnel_type = form.save()
            previous_values, new_values = changed_values(
                previous_values_full,
                snapshot_instance(funnel_type, FUNNEL_TYPE_AUDIT_FIELDS),
            )
            if previous_active and not funnel_type.active:
                action = 'Tipo de funil desativado'
            elif not previous_active and funnel_type.active:
                action = 'Tipo de funil ativado'
            else:
                action = 'Tipo de funil atualizado'
            log_activity(
                actor=request.user,
                obj=funnel_type,
                action=action,
                object_label=funnel_type.name,
                details=f'Tipo de funil: {funnel_type.name}; código: {funnel_type.code}; ativo: {funnel_type.active}',
                previous_values=previous_values,
                new_values=new_values,
            )
            messages.success(request, 'Tipo de funil atualizado.')
            return redirect('commercial_funnel_types')
    else:
        form = FunnelTypeForm(instance=funnel_type)

    return render(request, 'checklists/funnel_type_form.html', {
        'form': form,
        'title': f'Editar tipo de funil - {funnel_type.name}',
        'submit_label': 'Salvar alterações',
        'funnel_type': funnel_type,
        'is_admin': True,
    })


@require_POST
@user_passes_test(_admin_check)
def funnel_type_toggle(request, funnel_type_id):
    funnel_type = get_object_or_404(FunnelType, pk=funnel_type_id)
    previous_values_full = snapshot_instance(funnel_type, FUNNEL_TYPE_AUDIT_FIELDS)
    funnel_type.active = not funnel_type.active
    funnel_type.save(update_fields=['active', 'updated_at'])
    previous_values, new_values = changed_values(
        previous_values_full,
        snapshot_instance(funnel_type, FUNNEL_TYPE_AUDIT_FIELDS),
    )
    action = 'Tipo de funil ativado' if funnel_type.active else 'Tipo de funil desativado'
    log_activity(
        actor=request.user,
        obj=funnel_type,
        action=action,
        object_label=funnel_type.name,
        details=f'Tipo de funil: {funnel_type.name}; código: {funnel_type.code}; ativo: {funnel_type.active}',
        previous_values=previous_values,
        new_values=new_values,
    )
    messages.success(request, f'Tipo de funil {"ativado" if funnel_type.active else "desativado"}.')
    return redirect('commercial_funnel_types')


@user_passes_test(_admin_check)
def funnel_type_delete(request, funnel_type_id):
    funnel_type = get_object_or_404(FunnelType, pk=funnel_type_id)
    if funnel_type.has_funnel_usage():
        messages.error(request, 'Este tipo de funil já está sendo usado e não pode ser excluído.')
        return redirect('commercial_funnel_types')

    if request.method == 'POST':
        previous_values = snapshot_instance(funnel_type, FUNNEL_TYPE_AUDIT_FIELDS)
        object_id = str(funnel_type.id)
        object_label = funnel_type.name
        try:
            funnel_type.delete()
        except ProtectedError:
            messages.error(request, 'Este tipo de funil possui vínculos protegidos e não pode ser excluído.')
            return redirect('commercial_funnel_types')

        log_activity(
            actor=request.user,
            action='Tipo de funil excluído',
            object_type='FunnelType',
            object_id=object_id,
            object_label=object_label,
            details=f'Tipo de funil excluído: {object_label}',
            previous_values=previous_values,
        )
        messages.success(request, 'Tipo de funil excluído.')
        return redirect('commercial_funnel_types')

    return render(request, 'checklists/funnel_type_confirm_delete.html', {
        'funnel_type': funnel_type,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def funnel_stages_list(request):
    status = request.GET.get('status', 'ativas')
    stages = FunnelStage.objects.all().order_by('order', 'name')
    if status == 'inativas':
        stages = stages.filter(active=False)
    elif status != 'todas':
        status = 'ativas'
        stages = stages.filter(active=True)

    stages = list(stages)
    for stage in stages:
        stage.can_delete_from_ui = stage.can_be_deleted()

    return render(request, 'checklists/funnel_stages_list.html', {
        'stages': stages,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def funnel_stage_create(request):
    if request.method == 'POST':
        form = FunnelStageForm(request.POST)
        if form.is_valid():
            stage = form.save()
            log_activity(
                actor=request.user,
                obj=stage,
                action='Etapa de funil criada',
                object_label=stage.name,
                details=f'Etapa: {stage.name}; código: {stage.code}; ativo: {stage.active}',
                new_values=snapshot_instance(stage, FUNNEL_STAGE_AUDIT_FIELDS),
            )
            messages.success(request, 'Etapa de funil criada.')
            return redirect('commercial_funnel_stages')
    else:
        form = FunnelStageForm()

    return render(request, 'checklists/funnel_stage_form.html', {
        'form': form,
        'title': 'Inserir etapa de funil',
        'submit_label': 'Inserir etapa',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def funnel_stage_edit(request, stage_id):
    stage = get_object_or_404(FunnelStage, pk=stage_id)
    previous_active = stage.active
    previous_values_full = snapshot_instance(stage, FUNNEL_STAGE_AUDIT_FIELDS)
    if request.method == 'POST':
        form = FunnelStageForm(request.POST, instance=stage)
        if form.is_valid():
            stage = form.save()
            previous_values, new_values = changed_values(
                previous_values_full,
                snapshot_instance(stage, FUNNEL_STAGE_AUDIT_FIELDS),
            )
            if previous_active and not stage.active:
                action = 'Etapa de funil desativada'
            elif not previous_active and stage.active:
                action = 'Etapa de funil ativada'
            else:
                action = 'Etapa de funil atualizada'
            log_activity(
                actor=request.user,
                obj=stage,
                action=action,
                object_label=stage.name,
                details=f'Etapa: {stage.name}; código: {stage.code}; ativo: {stage.active}',
                previous_values=previous_values,
                new_values=new_values,
            )
            messages.success(request, 'Etapa de funil atualizada.')
            return redirect('commercial_funnel_stages')
    else:
        form = FunnelStageForm(instance=stage)

    return render(request, 'checklists/funnel_stage_form.html', {
        'form': form,
        'title': f'Editar etapa de funil - {stage.name}',
        'submit_label': 'Salvar alterações',
        'stage': stage,
        'is_admin': True,
    })


@require_POST
@user_passes_test(_admin_check)
def funnel_stage_toggle(request, stage_id):
    stage = get_object_or_404(FunnelStage, pk=stage_id)
    previous_values_full = snapshot_instance(stage, FUNNEL_STAGE_AUDIT_FIELDS)
    stage.active = not stage.active
    stage.save(update_fields=['active', 'updated_at'])
    previous_values, new_values = changed_values(
        previous_values_full,
        snapshot_instance(stage, FUNNEL_STAGE_AUDIT_FIELDS),
    )
    action = 'Etapa de funil ativada' if stage.active else 'Etapa de funil desativada'
    log_activity(
        actor=request.user,
        obj=stage,
        action=action,
        object_label=stage.name,
        details=f'Etapa: {stage.name}; código: {stage.code}; ativo: {stage.active}',
        previous_values=previous_values,
        new_values=new_values,
    )
    messages.success(request, f'Etapa {"ativada" if stage.active else "desativada"}.')
    return redirect('commercial_funnel_stages')


@user_passes_test(_admin_check)
def funnel_stage_delete(request, stage_id):
    stage = get_object_or_404(FunnelStage, pk=stage_id)
    if stage.has_usage():
        messages.error(request, 'Esta etapa já está sendo usada em modelos de funis e não pode ser excluída.')
        return redirect('commercial_funnel_stages')

    if request.method == 'POST':
        previous_values = snapshot_instance(stage, FUNNEL_STAGE_AUDIT_FIELDS)
        object_id = str(stage.id)
        object_label = stage.name
        try:
            stage.delete()
        except ProtectedError:
            messages.error(request, 'Esta etapa possui vínculos protegidos e não pode ser excluída.')
            return redirect('commercial_funnel_stages')
        log_activity(
            actor=request.user,
            action='Etapa de funil excluída',
            object_type='FunnelStage',
            object_id=object_id,
            object_label=object_label,
            details=f'Etapa excluída: {object_label}',
            previous_values=previous_values,
        )
        messages.success(request, 'Etapa de funil excluída.')
        return redirect('commercial_funnel_stages')

    return _confirm_delete(
        request,
        title='Excluir etapa de funil',
        object_label=stage.name,
        warning='A exclusão só é permitida quando a etapa nunca foi usada em modelos de funis.',
        cancel_url='commercial_funnel_stages',
    )


@user_passes_test(_admin_check)
def opportunity_origins_list(request):
    status = request.GET.get('status', 'ativas')
    origins = OpportunityOrigin.objects.all().order_by('-active', 'name')
    if status == 'inativas':
        origins = origins.filter(active=False)
    elif status != 'todas':
        status = 'ativas'
        origins = origins.filter(active=True)

    origins = list(origins)
    for origin in origins:
        origin.can_delete_from_ui = origin.can_be_deleted()

    return render(request, 'checklists/opportunity_origins_list.html', {
        'origins': origins,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def opportunity_origin_create(request):
    if request.method == 'POST':
        form = OpportunityOriginForm(request.POST)
        if form.is_valid():
            origin = form.save()
            log_activity(
                actor=request.user,
                obj=origin,
                action='Origem de oportunidade criada',
                object_label=origin.name,
                details=f'Origem: {origin.name}; código: {origin.code}; ativa: {origin.active}',
                new_values=snapshot_instance(origin, OPPORTUNITY_ORIGIN_AUDIT_FIELDS),
            )
            messages.success(request, 'Origem de oportunidade criada.')
            return redirect('commercial_opportunity_origins')
    else:
        form = OpportunityOriginForm()

    return render(request, 'checklists/opportunity_origin_form.html', {
        'form': form,
        'title': 'Inserir origem de oportunidade',
        'submit_label': 'Inserir origem',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def opportunity_origin_edit(request, origin_id):
    origin = get_object_or_404(OpportunityOrigin, pk=origin_id)
    previous_active = origin.active
    previous_values_full = snapshot_instance(origin, OPPORTUNITY_ORIGIN_AUDIT_FIELDS)
    if request.method == 'POST':
        form = OpportunityOriginForm(request.POST, instance=origin)
        if form.is_valid():
            origin = form.save()
            previous_values, new_values = changed_values(
                previous_values_full,
                snapshot_instance(origin, OPPORTUNITY_ORIGIN_AUDIT_FIELDS),
            )
            if previous_active and not origin.active:
                action = 'Origem de oportunidade desativada'
            elif not previous_active and origin.active:
                action = 'Origem de oportunidade ativada'
            else:
                action = 'Origem de oportunidade atualizada'
            log_activity(
                actor=request.user,
                obj=origin,
                action=action,
                object_label=origin.name,
                details=f'Origem: {origin.name}; código: {origin.code}; ativa: {origin.active}',
                previous_values=previous_values,
                new_values=new_values,
            )
            messages.success(request, 'Origem de oportunidade atualizada.')
            return redirect('commercial_opportunity_origins')
    else:
        form = OpportunityOriginForm(instance=origin)

    return render(request, 'checklists/opportunity_origin_form.html', {
        'form': form,
        'title': f'Editar origem de oportunidade - {origin.name}',
        'submit_label': 'Salvar alterações',
        'origin': origin,
        'is_admin': True,
    })


@require_POST
@user_passes_test(_admin_check)
def opportunity_origin_toggle(request, origin_id):
    origin = get_object_or_404(OpportunityOrigin, pk=origin_id)
    previous_values_full = snapshot_instance(origin, OPPORTUNITY_ORIGIN_AUDIT_FIELDS)
    origin.active = not origin.active
    origin.save(update_fields=['active', 'updated_at'])
    previous_values, new_values = changed_values(
        previous_values_full,
        snapshot_instance(origin, OPPORTUNITY_ORIGIN_AUDIT_FIELDS),
    )
    action = 'Origem de oportunidade ativada' if origin.active else 'Origem de oportunidade desativada'
    log_activity(
        actor=request.user,
        obj=origin,
        action=action,
        object_label=origin.name,
        details=f'Origem: {origin.name}; código: {origin.code}; ativa: {origin.active}',
        previous_values=previous_values,
        new_values=new_values,
    )
    messages.success(request, f'Origem {"ativada" if origin.active else "desativada"}.')
    return redirect('commercial_opportunity_origins')


@user_passes_test(_admin_check)
def opportunity_origin_delete(request, origin_id):
    origin = get_object_or_404(OpportunityOrigin, pk=origin_id)
    if origin.has_usage():
        messages.error(request, 'Esta origem já está sendo usada em modelos de funis e não pode ser excluída.')
        return redirect('commercial_opportunity_origins')

    if request.method == 'POST':
        previous_values = snapshot_instance(origin, OPPORTUNITY_ORIGIN_AUDIT_FIELDS)
        object_id = str(origin.id)
        object_label = origin.name
        try:
            origin.delete()
        except ProtectedError:
            messages.error(request, 'Esta origem possui vínculos protegidos e não pode ser excluída.')
            return redirect('commercial_opportunity_origins')
        log_activity(
            actor=request.user,
            action='Origem de oportunidade excluída',
            object_type='OpportunityOrigin',
            object_id=object_id,
            object_label=object_label,
            details=f'Origem excluída: {object_label}',
            previous_values=previous_values,
        )
        messages.success(request, 'Origem de oportunidade excluída.')
        return redirect('commercial_opportunity_origins')

    return _confirm_delete(
        request,
        title='Excluir origem de oportunidade',
        object_label=origin.name,
        warning='A exclusão só é permitida quando a origem nunca foi usada em modelos de funis.',
        cancel_url='commercial_opportunity_origins',
    )


@user_passes_test(_admin_check)
def funnel_models_list(request):
    status = request.GET.get('status', 'ativos')
    models = (
        FunnelModel.objects.prefetch_related('fields')
        .order_by('name')
    )
    if status == 'inativos':
        models = models.filter(active=False)
    elif status != 'todos':
        status = 'ativos'
        models = models.filter(active=True)
    models = list(models)
    for funnel_model in models:
        funnel_model.can_delete_from_ui = funnel_model.can_be_deleted()

    return render(request, 'checklists/funnel_models_list.html', {
        'funnel_models': models,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def funnel_model_create(request):
    funnel_model = FunnelModel()
    if request.method == 'POST':
        form = FunnelModelForm(request.POST, instance=funnel_model)
        formset = FunnelModelFieldFormSet(request.POST, instance=funnel_model, prefix='custom_fields')
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                funnel_model = form.save()
                formset.instance = funnel_model
                formset.save()
                log_activity(
                    actor=request.user,
                    obj=funnel_model,
                    action='Modelo de funil criado',
                    object_label=str(funnel_model),
                    details=f'Modelo de funil: {funnel_model}',
                    new_values=_funnel_model_snapshot(funnel_model),
                )
            messages.success(request, 'Modelo de funil criado.')
            return redirect('commercial_funnel_models')
    else:
        form = FunnelModelForm(instance=funnel_model)
        formset = FunnelModelFieldFormSet(instance=funnel_model, prefix='custom_fields')

    return render(request, 'checklists/funnel_model_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Inserir modelo de funil',
        'submit_label': 'Inserir modelo',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def funnel_model_edit(request, model_id):
    funnel_model = get_object_or_404(
        FunnelModel.objects.prefetch_related('fields'),
        pk=model_id,
    )
    previous_active = funnel_model.active
    previous_values_full = _funnel_model_snapshot(funnel_model)
    if request.method == 'POST':
        form = FunnelModelForm(request.POST, instance=funnel_model)
        formset = FunnelModelFieldFormSet(request.POST, instance=funnel_model, prefix='custom_fields')
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                funnel_model = form.save()
                formset.save()
                funnel_model = (
                    FunnelModel.objects.prefetch_related('fields').get(pk=funnel_model.pk)
                )
                previous_values, new_values = changed_values(
                    previous_values_full,
                    _funnel_model_snapshot(funnel_model),
                )
                if previous_active and not funnel_model.active:
                    action = 'Modelo de funil desativado'
                elif not previous_active and funnel_model.active:
                    action = 'Modelo de funil ativado'
                else:
                    action = 'Modelo de funil atualizado'
                log_activity(
                    actor=request.user,
                    obj=funnel_model,
                    action=action,
                    object_label=str(funnel_model),
                    details=f'Modelo de funil: {funnel_model}',
                    previous_values=previous_values,
                    new_values=new_values,
                )
            messages.success(request, 'Modelo de funil atualizado.')
            return redirect('commercial_funnel_models')
    else:
        form = FunnelModelForm(instance=funnel_model)
        formset = FunnelModelFieldFormSet(instance=funnel_model, prefix='custom_fields')

    return render(request, 'checklists/funnel_model_form.html', {
        'form': form,
        'formset': formset,
        'title': f'Editar modelo de funil - {funnel_model}',
        'submit_label': 'Salvar alterações',
        'funnel_model': funnel_model,
        'is_admin': True,
    })


@require_POST
@user_passes_test(_admin_check)
def funnel_model_toggle(request, model_id):
    funnel_model = get_object_or_404(
        FunnelModel.objects.prefetch_related('fields'),
        pk=model_id,
    )
    previous_values_full = _funnel_model_snapshot(funnel_model)
    funnel_model.active = not funnel_model.active
    funnel_model.save(update_fields=['active', 'updated_at'])
    funnel_model = (
        FunnelModel.objects.prefetch_related('fields').get(pk=funnel_model.pk)
    )
    previous_values, new_values = changed_values(
        previous_values_full,
        _funnel_model_snapshot(funnel_model),
    )
    action = 'Modelo de funil ativado' if funnel_model.active else 'Modelo de funil desativado'
    log_activity(
        actor=request.user,
        obj=funnel_model,
        action=action,
        object_label=str(funnel_model),
        details=f'Modelo de funil: {funnel_model}',
        previous_values=previous_values,
        new_values=new_values,
    )
    messages.success(request, f'Modelo de funil {"ativado" if funnel_model.active else "desativado"}.')
    return redirect('commercial_funnel_models')


@user_passes_test(_admin_check)
def funnel_model_delete(request, model_id):
    funnel_model = get_object_or_404(
        FunnelModel.objects.prefetch_related('fields'),
        pk=model_id,
    )
    if funnel_model.has_instantiated_funnels():
        messages.error(request, 'Este modelo já possui funis instanciados e não pode ser excluído.')
        return redirect('commercial_funnel_models')

    if request.method == 'POST':
        previous_values = _funnel_model_snapshot(funnel_model)
        object_id = str(funnel_model.id)
        object_label = str(funnel_model)
        try:
            funnel_model.delete()
        except ProtectedError:
            messages.error(request, 'Este modelo possui vínculos protegidos e não pode ser excluído.')
            return redirect('commercial_funnel_models')
        log_activity(
            actor=request.user,
            action='Modelo de funil excluído',
            object_type='FunnelModel',
            object_id=object_id,
            object_label=object_label,
            details=f'Modelo de funil excluído: {object_label}',
            previous_values=previous_values,
        )
        messages.success(request, 'Modelo de funil excluído.')
        return redirect('commercial_funnel_models')

    return _confirm_delete(
        request,
        title='Excluir modelo de funil',
        object_label=str(funnel_model),
        warning='A exclusão só é permitida se não houver funis instanciados usando este modelo.',
        cancel_url='commercial_funnel_models',
    )


@user_passes_test(_commercial_access_check)
def commercial_opportunities_list(request):
    status = request.GET.get('status', 'ativos')
    funnel_type_id = request.GET.get('tipo', '')
    stage_id = request.GET.get('etapa', '')
    funnel_id = request.GET.get('funil', '')
    opportunities = (
        _scope_commercial_opportunities(_commercial_opportunity_queryset(), request.user)
        .order_by(
            'funnel_type__name',
            'stage__order',
            'stage__name',
            'commercial_funnel__name',
            'title',
        )
    )

    if status == 'inativos':
        opportunities = opportunities.filter(active=False)
    elif status != 'todos':
        status = 'ativos'
        opportunities = opportunities.filter(active=True)

    if funnel_type_id and funnel_type_id.isdigit():
        opportunities = opportunities.filter(funnel_type_id=funnel_type_id)
    else:
        funnel_type_id = ''

    if stage_id and stage_id.isdigit():
        opportunities = opportunities.filter(stage_id=stage_id)
    else:
        stage_id = ''

    if funnel_id and funnel_id.isdigit():
        opportunities = opportunities.filter(commercial_funnel_id=funnel_id)
    else:
        funnel_id = ''

    opportunities = list(opportunities)
    for opportunity in opportunities:
        opportunity.custom_values = _opportunity_custom_values(opportunity)

    return render(request, 'checklists/commercial_opportunities_list.html', {
        'opportunities': opportunities,
        'opportunity_count': len(opportunities),
        'funnel_types': FunnelType.objects.all().order_by('name'),
        'stages': FunnelStage.objects.all().order_by('order', 'name'),
        'funnels': CommercialFunnel.objects.select_related('funnel_model').order_by('name'),
        'status': status,
        'funnel_type_id': funnel_type_id,
        'stage_id': stage_id,
        'funnel_id': funnel_id,
        'is_admin': _is_commercial_admin_context(request.user),
        'is_commercial_operator': _is_commercial_operator(request.user),
    })


@user_passes_test(_commercial_access_check)
def commercial_opportunity_create(request):
    week_start = _parse_week_start(
        request.POST.get('trial_lesson_week') if request.method == 'POST' else request.GET.get('semana')
    )
    trial_lesson_course = _trial_lesson_course_from_request(request)
    slots = _available_trial_slots(week_start, course=trial_lesson_course)
    calendar_slots = _trial_calendar_slots(week_start)
    if request.method == 'POST':
        generated_code = next_commercial_opportunity_code()
        post_data = request.POST.copy()
        post_data['title'] = generated_code
        if not post_data.get('owner') and _is_commercial_operator(request.user):
            post_data['owner'] = str(request.user.pk)
        form = CommercialOpportunityForm(post_data, available_trial_slots=slots, generated_title=generated_code)
        if form.is_valid():
            try:
                with transaction.atomic():
                    opportunity = form.save(commit=False)
                    opportunity.title = generated_code
                    _apply_opportunity_business_rules(opportunity, form=form)
                    opportunity.save()
                    opportunity = _commercial_opportunity_queryset().get(pk=opportunity.pk)
                    lesson = _build_trial_lesson_from_form(opportunity=opportunity, form=form, actor=request.user)
                    if lesson:
                        lesson.save()
                        _log_trial_lesson_created(actor=request.user, lesson=lesson)
                    _record_stage_event(
                        opportunity=opportunity,
                        actor=request.user,
                        previous_stage=None,
                        note='Etapa inicial da oportunidade.',
                    )
                    _record_follow_up_event(
                        opportunity=opportunity,
                        actor=request.user,
                        previous_date=None,
                        note='Follow-up inicial da oportunidade.',
                    )
                    log_activity(
                        actor=request.user,
                        obj=opportunity,
                        action='Oportunidade comercial criada',
                        object_label=opportunity.title,
                        details=f'Oportunidade: {opportunity.title}; funil: {opportunity.commercial_funnel}; ativa: {opportunity.active}',
                        new_values=_commercial_opportunity_snapshot(opportunity),
                    )
                messages.success(request, 'Oportunidade criada.')
                return redirect(_commercial_redirect_name(request.user))
            except ValidationError as exc:
                form.add_error('trial_lesson_slot', '; '.join(exc.messages))
    else:
        initial = {
            'title': next_commercial_opportunity_code(),
            'owner': request.user.pk if _is_commercial_operator(request.user) else None,
            'next_follow_up_date': timezone.localdate() + timedelta(days=1),
        }
        funnel_id = request.GET.get('funil')
        if funnel_id and funnel_id.isdigit():
            initial['commercial_funnel'] = funnel_id
        form = CommercialOpportunityForm(initial=initial, available_trial_slots=slots, generated_title=initial['title'])

    return render(request, 'checklists/commercial_opportunity_form.html', _commercial_form_context(
        request,
        form=form,
        title='Criar oportunidade',
        submit_label='Criar oportunidade',
        week_start=week_start,
        slots=calendar_slots,
    ))


@user_passes_test(_commercial_access_check)
def commercial_opportunity_edit(request, opportunity_id):
    opportunity = get_object_or_404(_scope_commercial_opportunities(_commercial_opportunity_queryset(), request.user), pk=opportunity_id)
    week_start = _parse_week_start(
        request.POST.get('trial_lesson_week') if request.method == 'POST' else request.GET.get('semana')
    )
    trial_lesson_course = _trial_lesson_course_from_request(request)
    slots = _available_trial_slots(week_start, course=trial_lesson_course)
    calendar_slots = _trial_calendar_slots(week_start)
    previous_active = opportunity.active
    previous_stage = opportunity.stage
    previous_stage_id = opportunity.stage_id
    previous_follow_up_date = opportunity.next_follow_up_date
    previous_values_full = _commercial_opportunity_snapshot(opportunity)
    has_existing_trial_lesson = opportunity.trial_lessons.exists()
    if request.method == 'POST':
        post_data = request.POST.copy()
        post_data['title'] = opportunity.title
        if not post_data.get('owner'):
            post_data['owner'] = str(opportunity.owner_id or request.user.pk)
        form = CommercialOpportunityForm(
            post_data,
            instance=opportunity,
            available_trial_slots=slots,
            has_existing_trial_lesson=has_existing_trial_lesson,
        )
        if form.is_valid():
            try:
                with transaction.atomic():
                    opportunity = form.save(commit=False)
                    _apply_opportunity_business_rules(opportunity, form=form)
                    opportunity.save()
                    opportunity = _commercial_opportunity_queryset().get(pk=opportunity.pk)
                    lesson = _build_trial_lesson_from_form(opportunity=opportunity, form=form, actor=request.user)
                    if lesson:
                        lesson.save()
                        _log_trial_lesson_created(actor=request.user, lesson=lesson)
                    if previous_stage_id != opportunity.stage_id:
                        _record_stage_event(
                            opportunity=opportunity,
                            actor=request.user,
                            previous_stage=previous_stage,
                            note='Etapa alterada na edição da oportunidade.',
                        )
                    if previous_follow_up_date != opportunity.next_follow_up_date:
                        _record_follow_up_event(
                            opportunity=opportunity,
                            actor=request.user,
                            previous_date=previous_follow_up_date,
                            note='Data do próximo follow-up alterada.',
                        )
                    previous_values, new_values = changed_values(
                        previous_values_full,
                        _commercial_opportunity_snapshot(opportunity),
                    )
                    if previous_active and not opportunity.active:
                        action = 'Oportunidade comercial desativada'
                    elif not previous_active and opportunity.active:
                        action = 'Oportunidade comercial ativada'
                    else:
                        action = 'Oportunidade comercial atualizada'
                    log_activity(
                        actor=request.user,
                        obj=opportunity,
                        action=action,
                        object_label=opportunity.title,
                        details=f'Oportunidade: {opportunity.title}; funil: {opportunity.commercial_funnel}; ativa: {opportunity.active}',
                        previous_values=previous_values,
                        new_values=new_values,
                    )
                messages.success(request, 'Oportunidade atualizada.')
                return redirect(_commercial_redirect_name(request.user))
            except ValidationError as exc:
                form.add_error('trial_lesson_slot', '; '.join(exc.messages))
    else:
        form = CommercialOpportunityForm(
            instance=opportunity,
            available_trial_slots=slots,
            has_existing_trial_lesson=has_existing_trial_lesson,
        )

    return render(request, 'checklists/commercial_opportunity_form.html', _commercial_form_context(
        request,
        form=form,
        title=f'Editar oportunidade - {opportunity.title}',
        submit_label='Salvar alterações',
        opportunity=opportunity,
        week_start=week_start,
        slots=calendar_slots,
        extra={
            'follow_up_events': opportunity.follow_up_events.select_related('actor')[:20],
            'stage_events': opportunity.stage_events.select_related('actor', 'previous_stage', 'new_stage')[:20],
            'trial_lessons': opportunity.trial_lessons.select_related('course', 'room').order_by('-date', '-start_time')[:20],
        },
    ))


@require_POST
@user_passes_test(_commercial_access_check)
def commercial_opportunity_toggle(request, opportunity_id):
    opportunity = get_object_or_404(_scope_commercial_opportunities(_commercial_opportunity_queryset(), request.user), pk=opportunity_id)
    previous_values_full = _commercial_opportunity_snapshot(opportunity)
    opportunity.active = not opportunity.active
    opportunity.save(update_fields=['active', 'updated_at'])
    opportunity = _commercial_opportunity_queryset().get(pk=opportunity.pk)
    previous_values, new_values = changed_values(
        previous_values_full,
        _commercial_opportunity_snapshot(opportunity),
    )
    action = 'Oportunidade comercial ativada' if opportunity.active else 'Oportunidade comercial desativada'
    log_activity(
        actor=request.user,
        obj=opportunity,
        action=action,
        object_label=opportunity.title,
        details=f'Oportunidade: {opportunity.title}; funil: {opportunity.commercial_funnel}; ativa: {opportunity.active}',
        previous_values=previous_values,
        new_values=new_values,
    )
    messages.success(request, f'Oportunidade {"ativada" if opportunity.active else "desativada"}.')
    return redirect(_commercial_redirect_name(request.user))


@user_passes_test(_admin_check)
def commercial_funnels_list(request):
    status = request.GET.get('status', 'ativos')
    model_id = request.GET.get('modelo')
    funnels = (
        CommercialFunnel.objects.select_related('funnel_model')
        .order_by('name')
    )
    if status == 'inativos':
        funnels = funnels.filter(active=False)
    elif status != 'todos':
        status = 'ativos'
        funnels = funnels.filter(active=True)
    if model_id and model_id.isdigit():
        funnels = funnels.filter(funnel_model_id=model_id)

    return render(request, 'checklists/commercial_funnels_list.html', {
        'funnels': funnels,
        'models': FunnelModel.objects.order_by('name'),
        'status': status,
        'model_id': model_id or '',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def commercial_funnel_create(request):
    if request.method == 'POST':
        form = CommercialFunnelForm(request.POST)
        if form.is_valid():
            funnel = form.save()
            log_activity(
                actor=request.user,
                obj=funnel,
                action='Funil comercial criado',
                object_label=funnel.name,
                details=f'Funil: {funnel.name}; modelo: {funnel.funnel_model}; ativo: {funnel.active}',
                new_values=snapshot_instance(funnel, COMMERCIAL_FUNNEL_AUDIT_FIELDS),
            )
            messages.success(request, 'Funil criado.')
            return redirect('commercial_funnels')
    else:
        form = CommercialFunnelForm()

    return render(request, 'checklists/commercial_funnel_form.html', {
        'form': form,
        'title': 'Criar funil',
        'submit_label': 'Criar funil',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def commercial_funnel_edit(request, funnel_id):
    funnel = get_object_or_404(
        CommercialFunnel.objects.select_related('funnel_model'),
        pk=funnel_id,
    )
    previous_active = funnel.active
    previous_values_full = snapshot_instance(funnel, COMMERCIAL_FUNNEL_AUDIT_FIELDS)
    if request.method == 'POST':
        form = CommercialFunnelForm(request.POST, instance=funnel)
        if form.is_valid():
            funnel = form.save()
            previous_values, new_values = changed_values(
                previous_values_full,
                snapshot_instance(funnel, COMMERCIAL_FUNNEL_AUDIT_FIELDS),
            )
            if previous_active and not funnel.active:
                action = 'Funil comercial desativado'
            elif not previous_active and funnel.active:
                action = 'Funil comercial ativado'
            else:
                action = 'Funil comercial atualizado'
            log_activity(
                actor=request.user,
                obj=funnel,
                action=action,
                object_label=funnel.name,
                details=f'Funil: {funnel.name}; modelo: {funnel.funnel_model}; ativo: {funnel.active}',
                previous_values=previous_values,
                new_values=new_values,
            )
            messages.success(request, 'Funil atualizado.')
            return redirect('commercial_funnels')
    else:
        form = CommercialFunnelForm(instance=funnel)

    return render(request, 'checklists/commercial_funnel_form.html', {
        'form': form,
        'title': f'Editar funil - {funnel.name}',
        'submit_label': 'Salvar alterações',
        'funnel': funnel,
        'is_admin': True,
    })


@require_POST
@user_passes_test(_admin_check)
def commercial_funnel_toggle(request, funnel_id):
    funnel = get_object_or_404(CommercialFunnel.objects.select_related('funnel_model'), pk=funnel_id)
    previous_values_full = snapshot_instance(funnel, COMMERCIAL_FUNNEL_AUDIT_FIELDS)
    funnel.active = not funnel.active
    funnel.save(update_fields=['active', 'updated_at'])
    previous_values, new_values = changed_values(
        previous_values_full,
        snapshot_instance(funnel, COMMERCIAL_FUNNEL_AUDIT_FIELDS),
    )
    action = 'Funil comercial ativado' if funnel.active else 'Funil comercial desativado'
    log_activity(
        actor=request.user,
        obj=funnel,
        action=action,
        object_label=funnel.name,
        details=f'Funil: {funnel.name}; modelo: {funnel.funnel_model}; ativo: {funnel.active}',
        previous_values=previous_values,
        new_values=new_values,
    )
    messages.success(request, f'Funil {"ativado" if funnel.active else "desativado"}.')
    return redirect('commercial_funnels')
