import csv
import json
from calendar import monthrange as calendar_monthrange
from datetime import datetime, timedelta
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.db.models import F, Q
from .audit import changed_values, log_activity, snapshot_instance
from .backup import (
    backup_runtime_status, download_remote_backup, get_backup_configuration,
    import_uploaded_backup, list_local_backups, list_remote_backups,
    restore_local_backup, run_backup, split_remote_path,
)
from .forms import (
    ActivityDeactivationSuggestionForm, ActivitySuggestionCreateForm,
    ActivitySuggestionReviewForm, AdminPasswordResetForm, BackupConfigurationForm,
    BackupUploadForm, DailyNoteForm, EmployeeCreateForm, EmployeeUpdateForm,
    MetricRecordForm, MetricTypeForm, OccurrenceUpdateForm, TaskTemplateForm,
)
from .models import (
    ActivityLog, ActivitySuggestion, BackupConfiguration, ChecklistOccurrence,
    ChecklistOccurrenceStatusEvent, DailyNote, EvidenceAttachment,
    MetricRecord, MetricType, Position, TaskTemplate, UserProfile,
)
from .activity_import import (
    build_activity_import_template, import_activity_rows, parse_activity_import,
)
from .services import (
    absence_for_user_on_date, create_due_occurrences, create_occurrences_for_positions,
    filter_absence_ignored_occurrences, get_user_position, is_admin_user,
    METRIC_PERIOD_CHOICES, METRIC_PERIOD_MONTHLY, metric_dashboard_data,
    month_range, monthly_summary, overdue_occurrences, position_absences_on_date,
    position_is_fully_absent_on_date, status_duration_summary, user_is_absent_on_date,
    visible_positions, working_days_between,
)

User = get_user_model()


TASK_TEMPLATE_AUDIT_FIELDS = [
    'position', 'day_of_week', 'start_time', 'end_time', 'title',
    'expected_result', 'frequency', 'requires_evidence', 'evidence_required',
    'proof_location', 'notes', 'active',
]
METRIC_TYPE_AUDIT_FIELDS = [
    'name', 'code', 'area', 'frequency', 'position', 'activity',
    'monthly_target', 'unit', 'active',
]
METRIC_RECORD_AUDIT_FIELDS = ['metric', 'position', 'date', 'executor_full_name', 'value', 'notes']
ACTIVITY_SUGGESTION_AUDIT_FIELDS = [
    'request_type', 'status', 'position', 'target_template', 'created_template',
    'title', 'expected_result', 'frequency', 'day_of_week', 'start_time',
    'end_time', 'requires_evidence', 'evidence_required', 'proof_location',
    'notes', 'justification', 'review_note', 'reviewed_by', 'reviewed_at',
]
BACKUP_CONFIG_AUDIT_FIELDS = ['cloud_provider', 'remote_path', 'retention_days', 'backup_time', 'active']


def _activity_return_url(request, occurrence):
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and next_url.startswith('/'):
        return next_url
    if is_admin_user(request.user):
        return f'{reverse("checklist_day")}?data={occurrence.date.isoformat()}&cargo={occurrence.position_id}'
    return f'{reverse("activities")}?periodo=dia&data={occurrence.date.isoformat()}'


def _parse_date(value):
    if not value:
        return timezone.localdate()
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return timezone.localdate()


def _parse_filter_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_month_year(request):
    today = timezone.localdate()
    year = int(request.GET.get('ano', today.year))
    month = int(request.GET.get('mes', today.month))
    return year, month


def _parse_metric_period(request):
    period = request.GET.get('periodo') or METRIC_PERIOD_MONTHLY
    if period not in dict(METRIC_PERIOD_CHOICES):
        period = METRIC_PERIOD_MONTHLY
    return period, _parse_date(request.GET.get('data'))


def _add_months(value, offset):
    month_index = value.month - 1 + offset
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar_monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _selected_position(request):
    positions = visible_positions(request.user)
    pos_id = request.GET.get('cargo')
    if pos_id and is_admin_user(request.user):
        return get_object_or_404(positions, pk=pos_id)
    return positions.first()


def _history_positions_for_user(user):
    if is_admin_user(user):
        return Position.objects.all().order_by('name')
    return visible_positions(user)


def _can_access_position_history(user, position):
    if is_admin_user(user):
        return True
    return visible_positions(user).filter(pk=position.pk).exists()


def _current_employee_name(user):
    """Retorna o nome completo do cadastro do usuário.

    Este valor é gravado como snapshot nos lançamentos para manter histórico,
    mesmo que o nome do usuário seja alterado posteriormente.
    """
    profile = getattr(user, 'userprofile', None)
    if profile and profile.display_name:
        return profile.display_name
    full = user.get_full_name().strip()
    return full or user.username


def _admin_check(user):
    return user.is_authenticated and is_admin_user(user)


def _role_initial(profile):
    if profile.system_role == UserProfile.ROLE_ADMIN:
        return 'ADMIN'
    if profile.position_id:
        return f'POSITION:{profile.position_id}'
    return ''


@login_required
def dashboard(request):
    if not is_admin_user(request.user):
        return redirect('operational_home')

    positions = Position.objects.all()
    profiles = UserProfile.objects.select_related('user', 'position')
    recent_logs = ActivityLog.objects.select_related('actor', 'position')[:12]

    return render(request, 'checklists/dashboard.html', {
        'active_positions_count': positions.filter(active=True).count(),
        'inactive_positions_count': positions.filter(active=False).count(),
        'admin_users_count': profiles.filter(system_role=UserProfile.ROLE_ADMIN, active=True, user__is_active=True).count(),
        'operator_users_count': profiles.filter(system_role=UserProfile.ROLE_OPERATOR, active=True, user__is_active=True).count(),
        'recent_logs': recent_logs,
        'backup_config': get_backup_configuration(),
        'is_admin': True,
    })


@login_required
def operational_home(request):
    if is_admin_user(request.user):
        return redirect('dashboard')
    profile = getattr(request.user, 'userprofile', None)
    return render(request, 'checklists/operational_home.html', {
        'profile': profile,
        'position': get_user_position(request.user),
        'is_admin': False,
    })


def _admin_module_placeholder(request, *, title, section):
    return render(request, 'checklists/admin_module_placeholder.html', {
        'title': title,
        'section': section,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def commercial_indicators(request):
    return _admin_module_placeholder(
        request,
        title='Indicadores',
        section='Gestão Comercial',
    )


@user_passes_test(_admin_check)
def commercial_goals(request):
    return _admin_module_placeholder(
        request,
        title='Metas',
        section='Gestão Comercial',
    )


@user_passes_test(_admin_check)
def pedagogical_class_schedule(request):
    return _admin_module_placeholder(
        request,
        title='Agenda de Aulas',
        section='Gestão Pedagógica > Aulas',
    )


@user_passes_test(_admin_check)
def pedagogical_feedback_models(request):
    return _admin_module_placeholder(
        request,
        title='Modelos de Feedback de Aula',
        section='Gestão Pedagógica > Aulas',
    )


@login_required
def activities(request):
    if is_admin_user(request.user):
        return redirect('dashboard')

    position = get_user_position(request.user)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado. Peça ao administrador para configurar o perfil.')

    period = request.GET.get('periodo', 'semana')
    if period not in {'dia', 'semana', 'mes'}:
        period = 'semana'

    reference_date = _parse_date(request.GET.get('data'))
    if period == 'semana':
        start_date = reference_date - timedelta(days=reference_date.weekday())
        end_date = start_date + timedelta(days=5)
        title = 'Atividades da semana'
    elif period == 'mes':
        start_date, end_date = month_range(reference_date.year, reference_date.month)
        title = 'Atividades do mês'
    else:
        start_date = end_date = reference_date
        title = 'Atividades do dia'

    if period == 'dia':
        days = [start_date]
    else:
        days = list(working_days_between(start_date, end_date))
    absences_by_day = {}
    for day in days:
        absence = absence_for_user_on_date(request.user, day)
        absences_by_day[day] = absence
        if not absence:
            create_due_occurrences(position, day, user=request.user)

    occurrences = filter_absence_ignored_occurrences(ChecklistOccurrence.objects.filter(
        position=position,
        date__range=(start_date, end_date),
    ).select_related('template', 'position').prefetch_related('attachments').order_by(
        'date', F('template__start_time').asc(nulls_last=True), 'template__order', 'template__title'
    ))

    grouped = []
    grouped_by_day = {}
    for day in days:
        absence = absences_by_day.get(day)
        items = [] if absence else [item for item in occurrences if item.date == day]
        grouped.append((day, items, absence))
        grouped_by_day[day] = {'date': day, 'items': items, 'absence': absence, 'in_period': True}

    if period == 'dia':
        calendar_rows = [[grouped_by_day[start_date]]]
        prev_period_date = reference_date - timedelta(days=1)
        next_period_date = reference_date + timedelta(days=1)
    elif period == 'semana':
        calendar_rows = [[grouped_by_day[day] for day in days]]
        prev_period_date = start_date - timedelta(days=7)
        next_period_date = start_date + timedelta(days=7)
    else:
        calendar_start = start_date + timedelta(days=1) if start_date.weekday() == 6 else start_date - timedelta(days=start_date.weekday())
        calendar_end = end_date - timedelta(days=1) if end_date.weekday() == 6 else end_date + timedelta(days=5 - end_date.weekday())
        calendar_rows = []
        current = calendar_start
        while current <= calendar_end:
            week = []
            for _ in range(6):
                cell = grouped_by_day.get(current, {
                    'date': current,
                    'items': [],
                    'absence': None,
                    'in_period': start_date <= current <= end_date,
                })
                cell['in_period'] = start_date <= current <= end_date
                week.append(cell)
                current += timedelta(days=1)
            calendar_rows.append(week)
        prev_period_date = _add_months(reference_date, -1)
        next_period_date = _add_months(reference_date, 1)

    return render(request, 'checklists/activities.html', {
        'title': title,
        'period': period,
        'period_options': [
            ('dia', 'Atividades do dia'),
            ('semana', 'Atividades da semana'),
            ('mes', 'Atividades do mês'),
        ],
        'reference_date': reference_date,
        'start_date': start_date,
        'end_date': end_date,
        'prev_period_date': prev_period_date,
        'next_period_date': next_period_date,
        'position': position,
        'grouped': grouped,
        'calendar_rows': calendar_rows,
        'statuses': ChecklistOccurrence.OPERATIONAL_STATUS_CHOICES,
        'employee_name': _current_employee_name(request.user),
        'is_admin': False,
    })


@login_required
def checklist_day(request):
    target_date = _parse_date(request.GET.get('data'))
    position = _selected_position(request)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado. Peça ao administrador para configurar o perfil.')

    user_absence = None if is_admin_user(request.user) else absence_for_user_on_date(request.user, target_date)
    position_fully_absent = position_is_fully_absent_on_date(position, target_date)
    position_absences = position_absences_on_date(position, target_date) if position_fully_absent else []

    if not user_absence:
        create_due_occurrences(position, target_date, user=None if is_admin_user(request.user) else request.user)
    occurrences = ChecklistOccurrence.objects.filter(position=position, date=target_date).select_related('template', 'position').order_by(F('template__start_time').asc(nulls_last=True), 'template__order', 'template__title')
    occurrences = [] if user_absence else filter_absence_ignored_occurrences(occurrences)
    note, _ = DailyNote.objects.get_or_create(position=position, date=target_date)

    if request.method == 'POST' and request.POST.get('form_type') == 'daily_note':
        if user_absence:
            return HttpResponseForbidden('Você está com ausência registrada para esta data.')
        form = DailyNoteForm(request.POST, instance=note)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.executor_full_name = _current_employee_name(request.user)
            obj.created_by = request.user
            obj.save()
            ActivityLog.objects.create(actor=request.user, position=position, action='Resumo diário atualizado', object_type='DailyNote', object_id=str(obj.id), details=f'Responsável: {obj.executor_full_name}')
            messages.success(request, 'Resumo diário salvo.')
            return redirect(f'{request.path}?data={target_date.isoformat()}&cargo={position.id}')
    else:
        form = DailyNoteForm(instance=note)

    return render(request, 'checklists/checklist_day.html', {
        'target_date': target_date,
        'position': position,
        'positions': visible_positions(request.user),
        'occurrences': occurrences,
        'statuses': ChecklistOccurrence.OPERATIONAL_STATUS_CHOICES,
        'employee_name': _current_employee_name(request.user),
        'note_form': form,
        'user_absence': user_absence,
        'position_absences': position_absences,
        'position_fully_absent': position_fully_absent,
        'is_admin': is_admin_user(request.user),
    })


@login_required
def week_view(request):
    selected = _parse_date(request.GET.get('data'))
    monday = selected - timedelta(days=selected.weekday())
    days = [monday + timedelta(days=i) for i in range(6)]
    position = _selected_position(request)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado.')

    absences_by_day = {}
    for day in days:
        absence = None if is_admin_user(request.user) else absence_for_user_on_date(request.user, day)
        absences_by_day[day] = absence
        if not absence:
            create_due_occurrences(position, day, user=None if is_admin_user(request.user) else request.user)

    grouped = []
    for day in days:
        items = ChecklistOccurrence.objects.filter(position=position, date=day).select_related('position', 'template').order_by(F('template__start_time').asc(nulls_last=True), 'template__order', 'template__title')
        absence = absences_by_day.get(day)
        if absence:
            grouped.append((day, [], absence, []))
        else:
            position_absences = position_absences_on_date(position, day) if position_is_fully_absent_on_date(position, day) else []
            grouped.append((day, filter_absence_ignored_occurrences(items), None, position_absences))

    return render(request, 'checklists/week_view.html', {
        'position': position,
        'positions': visible_positions(request.user),
        'monday': monday,
        'prev_week': monday - timedelta(days=7),
        'next_week': monday + timedelta(days=7),
        'grouped': grouped,
        'is_admin': is_admin_user(request.user),
    })


@login_required
def update_occurrence(request, occurrence_id):
    occurrence = get_object_or_404(ChecklistOccurrence.objects.select_related('position', 'template'), pk=occurrence_id)
    if not _can_access_position_history(request.user, occurrence.position):
        return HttpResponseForbidden('Você não pode alterar esta tarefa.')
    if request.method != 'POST':
        return redirect('checklist_day')
    if not is_admin_user(request.user) and user_is_absent_on_date(request.user, occurrence.date):
        return HttpResponseForbidden('Você está com ausência registrada para esta data.')

    form, saved = _save_occurrence_update(request, occurrence)
    if saved:
        messages.success(request, 'Tarefa atualizada.')
    else:
        messages.error(request, 'Não foi possível salvar. Verifique os campos.')
    return redirect(request.META.get('HTTP_REFERER') or _activity_return_url(request, occurrence))


@login_required
def occurrence_edit(request, occurrence_id):
    occurrence = get_object_or_404(
        ChecklistOccurrence.objects.select_related('position', 'template').prefetch_related('attachments'),
        pk=occurrence_id,
    )
    if not _can_access_position_history(request.user, occurrence.position):
        return HttpResponseForbidden('Você não pode alterar esta tarefa.')
    if not is_admin_user(request.user) and user_is_absent_on_date(request.user, occurrence.date):
        return HttpResponseForbidden('Você está com ausência registrada para esta data.')

    if request.method == 'POST':
        form, saved = _save_occurrence_update(request, occurrence)
        if saved:
            messages.success(request, 'Tarefa atualizada.')
            return redirect(_activity_return_url(request, occurrence))
        messages.error(request, 'Não foi possível salvar. Verifique os campos.')
    else:
        has_existing = bool(occurrence.evidence_file) or occurrence.attachments.exists()
        form = OccurrenceUpdateForm(
            instance=occurrence,
            has_existing_file=has_existing,
            requires_evidence=occurrence.template.requires_evidence,
        )

    return render(request, 'checklists/occurrence_form.html', {
        'occurrence': occurrence,
        'form': form,
        'return_url': _activity_return_url(request, occurrence),
        'status_events': occurrence.status_events.select_related('changed_by').order_by('-changed_at', '-id') if is_admin_user(request.user) else [],
        'status_duration_rows': status_duration_summary(occurrence) if is_admin_user(request.user) else [],
        'is_admin': is_admin_user(request.user),
    })


@login_required
def activity_suggestion_create(request):
    if is_admin_user(request.user):
        return redirect('templates_list')

    position = get_user_position(request.user)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado. Peça ao administrador para configurar o perfil.')

    if request.method == 'POST':
        form = ActivitySuggestionCreateForm(request.POST)
        if form.is_valid():
            suggestion = form.save(commit=False)
            suggestion.request_type = ActivitySuggestion.TYPE_CREATE
            suggestion.status = ActivitySuggestion.STATUS_PENDING
            suggestion.position = position
            suggestion.requested_by = request.user
            suggestion.save()
            log_activity(
                actor=request.user,
                obj=suggestion,
                position=position,
                action='Sugestão de atividade criada',
                object_label=suggestion.title,
                details=f'Atividade sugerida: {suggestion.title}; cargo: {position.name}',
                new_values=snapshot_instance(suggestion, ACTIVITY_SUGGESTION_AUDIT_FIELDS),
            )
            messages.success(request, 'Sugestão enviada para análise do administrador.')
            return redirect('activities')
    else:
        form = ActivitySuggestionCreateForm()

    return render(request, 'checklists/activity_suggestion_form.html', {
        'form': form,
        'position': position,
        'title': 'Sugerir nova atividade',
        'submit_label': 'Enviar sugestão',
        'is_admin': False,
    })


@login_required
def activity_suggestion_deactivate(request):
    if is_admin_user(request.user):
        return redirect('templates_list')

    position = get_user_position(request.user)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado. Peça ao administrador para configurar o perfil.')

    if request.method == 'POST':
        form = ActivityDeactivationSuggestionForm(request.POST, position=position)
        if form.is_valid():
            selected = list(form.cleaned_data['activities'])
            justification = form.cleaned_data.get('justification', '')
            created_count = 0
            skipped_count = 0
            for template in selected:
                existing = ActivitySuggestion.objects.filter(
                    request_type=ActivitySuggestion.TYPE_DEACTIVATE,
                    status=ActivitySuggestion.STATUS_PENDING,
                    position=position,
                    target_template=template,
                ).first()
                if existing:
                    skipped_count += 1
                    continue
                suggestion = ActivitySuggestion.objects.create(
                    request_type=ActivitySuggestion.TYPE_DEACTIVATE,
                    status=ActivitySuggestion.STATUS_PENDING,
                    position=position,
                    target_template=template,
                    requested_by=request.user,
                    justification=justification,
                )
                created_count += 1
                log_activity(
                    actor=request.user,
                    obj=suggestion,
                    position=position,
                    action='Sugestão de desativação criada',
                    object_label=template.title,
                    details=f'Atividade indicada: {template.title}; cargo: {position.name}',
                    new_values={
                        'target_template': {'id': template.id, 'label': template.title},
                        'justification': justification,
                    },
                )
            if created_count:
                messages.success(request, f'{created_count} sugestão(ões) enviada(s) para análise.')
            if skipped_count:
                messages.info(request, f'{skipped_count} atividade(s) já tinham sugestão pendente.')
            return redirect('activities')
    else:
        form = ActivityDeactivationSuggestionForm(position=position)

    return render(request, 'checklists/activity_deactivation_suggestion_form.html', {
        'form': form,
        'position': position,
        'title': 'Sugerir desativação de atividade',
        'submit_label': 'Enviar sugestão',
        'is_admin': False,
    })


def _save_occurrence_update(request, occurrence):
    old_status = occurrence.status
    has_existing = bool(occurrence.evidence_file) or occurrence.attachments.exists()
    requires_evidence = occurrence.template.requires_evidence
    form = OccurrenceUpdateForm(
        request.POST,
        request.FILES,
        instance=occurrence,
        has_existing_file=has_existing,
        requires_evidence=requires_evidence,
    )
    if form.is_valid():
        obj = form.save(commit=False)
        obj.executor_full_name = _current_employee_name(request.user)
        obj.mark_status(form.cleaned_data['status'], request.user)
        obj.save()
        if old_status != obj.status:
            ChecklistOccurrenceStatusEvent.objects.create(
                occurrence=obj,
                previous_status=old_status,
                new_status=obj.status,
                changed_by=request.user,
            )
        if requires_evidence:
            for uploaded in request.FILES.getlist('evidence_files'):
                EvidenceAttachment.objects.create(
                    occurrence=obj,
                    file=uploaded,
                    original_name=uploaded.name,
                    uploaded_by=request.user,
                )
        ActivityLog.objects.create(
            actor=request.user,
            position=obj.position,
            action='Tarefa atualizada',
            object_type='ChecklistOccurrence',
            object_id=str(obj.id),
            details=f'Status anterior: {old_status}; novo status: {obj.status}; executor: {obj.executor_full_name}; tarefa: {obj.template.title}',
        )
        return form, True
    return form, False


@login_required
def history(request):
    positions = _history_positions_for_user(request.user)
    qs = ChecklistOccurrence.objects.filter(position__in=positions).select_related('position', 'template').prefetch_related('attachments')

    start = request.GET.get('inicio')
    end = request.GET.get('fim')
    status = request.GET.get('status')
    cargo = request.GET.get('cargo')
    search = request.GET.get('busca')

    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    if status:
        qs = qs.filter(status=status)
    if cargo and is_admin_user(request.user):
        qs = qs.filter(position_id=cargo)
    if search:
        qs = qs.filter(
            Q(template__title__icontains=search) |
            Q(evidence_text__icontains=search) |
            Q(executor_full_name__icontains=search) |
            Q(blocked_reason__icontains=search)
        )

    qs = filter_absence_ignored_occurrences(qs.order_by('-date', 'position__name', 'template__order')[:1000])[:800]
    return render(request, 'checklists/history.html', {
        'occurrences': qs,
        'positions': positions,
        'statuses': ChecklistOccurrence.HISTORY_STATUS_CHOICES,
        'filters': {
            'inicio': start or '',
            'fim': end or '',
            'status': status or '',
            'cargo': cargo or '',
            'busca': search or '',
        },
        'done_status': ChecklistOccurrence.STATUS_DONE,
        'is_admin': is_admin_user(request.user),
    })


def _admin_activity_log_queryset(request):
    qs = ActivityLog.objects.select_related('actor', 'position').filter(
        Q(actor__is_staff=True) |
        Q(actor__is_superuser=True) |
        Q(actor__userprofile__system_role=UserProfile.ROLE_ADMIN)
    ).order_by('-created_at')

    start = _parse_filter_date(request.GET.get('inicio'))
    end = _parse_filter_date(request.GET.get('fim'))
    actor_id = request.GET.get('usuario')
    object_type = request.GET.get('tipo_objeto')
    action = request.GET.get('acao')
    search = request.GET.get('busca')

    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    if actor_id and actor_id.isdigit():
        qs = qs.filter(actor_id=actor_id)
    if object_type:
        qs = qs.filter(object_type=object_type)
    if action:
        qs = qs.filter(action=action)
    if search:
        qs = qs.filter(
            Q(action__icontains=search) |
            Q(object_type__icontains=search) |
            Q(object_id__icontains=search) |
            Q(object_label__icontains=search) |
            Q(details__icontains=search) |
            Q(actor__username__icontains=search) |
            Q(actor__first_name__icontains=search)
        )

    return qs


def _json_display(value, pretty=False):
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, indent=2 if pretty else None)


@user_passes_test(_admin_check)
def admin_activity_history(request):
    logs = list(_admin_activity_log_queryset(request)[:800])
    rows = [
        {
            'log': log,
            'previous_values_json': _json_display(log.previous_values, pretty=True),
            'new_values_json': _json_display(log.new_values, pretty=True),
        }
        for log in logs
    ]
    admin_users = User.objects.filter(
        Q(is_staff=True) | Q(is_superuser=True) | Q(userprofile__system_role=UserProfile.ROLE_ADMIN),
        activitylog__isnull=False,
    ).order_by('username').distinct()
    object_types = ActivityLog.objects.exclude(object_type='').order_by('object_type').values_list('object_type', flat=True).distinct()
    actions = ActivityLog.objects.exclude(action='').order_by('action').values_list('action', flat=True).distinct()

    return render(request, 'checklists/admin_activity_history.html', {
        'rows': rows,
        'admin_users': admin_users,
        'object_types': object_types,
        'actions': actions,
        'filters': {
            'inicio': request.GET.get('inicio', ''),
            'fim': request.GET.get('fim', ''),
            'usuario': request.GET.get('usuario', ''),
            'tipo_objeto': request.GET.get('tipo_objeto', ''),
            'acao': request.GET.get('acao', ''),
            'busca': request.GET.get('busca', ''),
        },
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def admin_activity_history_csv(request):
    logs = _admin_activity_log_queryset(request)[:5000]
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="historico_administrativo.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow([
        'Data/hora', 'Administrador', 'Cargo', 'Tipo de objeto', 'ID',
        'Nome/descrição', 'Ação', 'Valores anteriores', 'Valores novos', 'Detalhes',
    ])
    for log in logs:
        writer.writerow([
            timezone.localtime(log.created_at).strftime('%d/%m/%Y %H:%M:%S'),
            log.actor.username if log.actor else '',
            log.position.name if log.position else '',
            log.object_type,
            log.object_id,
            log.object_label,
            log.action,
            _json_display(log.previous_values),
            _json_display(log.new_values),
            log.details,
        ])
    return response


@user_passes_test(_admin_check)
def backups(request):
    config = get_backup_configuration()
    runtime = backup_runtime_status()
    rclone_remotes = runtime['rclone_remotes']
    upload_form = BackupUploadForm()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save':
            previous_values_full = snapshot_instance(config, BACKUP_CONFIG_AUDIT_FIELDS)
            form = BackupConfigurationForm(request.POST, instance=config, rclone_remotes=rclone_remotes)
            if form.is_valid():
                config = form.save(commit=False)
                config.updated_by = request.user
                config.save()
                previous_values, new_values = changed_values(
                    previous_values_full,
                    snapshot_instance(config, BACKUP_CONFIG_AUDIT_FIELDS),
                )
                log_activity(
                    actor=request.user,
                    action='Configuracao de backup atualizada',
                    obj=config,
                    previous_values=previous_values,
                    new_values=new_values,
                )
                messages.success(request, 'Configuração de backup salva.')
                return redirect('backups')
        elif action == 'upload_restore':
            upload_form = BackupUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                try:
                    result = import_uploaded_backup(upload_form.cleaned_data['backup_file'])
                except Exception as exc:
                    messages.error(request, f'Backup enviado não foi importado: {exc}')
                    return redirect('backups')
                log_activity(
                    actor=request.user,
                    action='Backup importado por upload',
                    obj=config,
                    new_values={
                        'backup_name': result.backup_name,
                        'local_path': str(result.local_path),
                        'has_media': result.has_media,
                    },
                )
                messages.success(request, f'Backup {result.backup_name} importado para a lista local. Ele já pode ser restaurado.')
                return redirect('backups')
        elif action == 'run':
            try:
                result = run_backup(config)
            except Exception as exc:
                log_activity(
                    actor=request.user,
                    action='Falha ao executar backup manual',
                    obj=config,
                    details=str(exc)[:1000],
                )
                messages.error(request, f'Backup não concluído: {exc}')
                return redirect('backups')

            log_activity(
                actor=request.user,
                action='Backup manual executado',
                obj=config,
                new_values={
                    'local_path': str(result.local_path),
                    'package_path': str(result.package_path) if result.package_path else '',
                    'cloud_status': result.cloud_status,
                    'cloud_message': result.cloud_message,
                },
            )
            if result.cloud_status == 'uploaded':
                messages.success(request, f'Backup gerado e enviado para {result.cloud_message}.')
            elif result.cloud_status in {'skipped', 'failed'}:
                messages.warning(request, f'Backup local gerado, mas envio para nuvem não ocorreu: {result.cloud_message}')
            else:
                messages.success(request, 'Backup local gerado. Envio para nuvem está desativado.')
            return redirect('backups')
        elif action == 'download_remote':
            backup_name = request.POST.get('backup_name', '')
            try:
                local_path = download_remote_backup(config, backup_name)
            except Exception as exc:
                messages.error(request, f'Backup não baixado da nuvem: {exc}')
                return redirect('backups')
            log_activity(
                actor=request.user,
                action='Backup baixado da nuvem',
                obj=config,
                new_values={'backup_name': backup_name, 'local_path': str(local_path)},
            )
            messages.success(request, f'Backup {backup_name} baixado para a lista local.')
            return redirect('backups')
        elif action == 'restore':
            backup_name = request.POST.get('backup_name', '')
            confirmation = request.POST.get('confirm_restore', '').strip().upper()
            restore_media = request.POST.get('restore_media') == 'on'
            if confirmation != 'RESTAURAR':
                messages.error(request, 'Digite RESTAURAR para confirmar a restauração.')
                return redirect('backups')
            try:
                result = restore_local_backup(backup_name, restore_media=restore_media)
            except Exception as exc:
                messages.error(request, f'Restauração não concluída: {exc}')
                return redirect('backups')
            try:
                log_activity(
                    actor=None,
                    action='Backup restaurado pela tela administrativa',
                    object_type='BackupRestore',
                    object_id=result.backup_name,
                    object_label=result.backup_name,
                    new_values={
                        'restored_path': str(result.restored_path),
                        'safety_backup_path': str(result.safety_backup_path) if result.safety_backup_path else '',
                        'restored_media': result.restored_media,
                    },
                )
            except Exception:
                pass
            messages.success(
                request,
                f'Backup {result.backup_name} restaurado. Backup de segurança antes da restauração: {result.safety_backup_path}.',
            )
            return redirect('backups')
        else:
            form = BackupConfigurationForm(instance=config, rclone_remotes=rclone_remotes)
            messages.error(request, 'Ação de backup inválida.')
    else:
        form = BackupConfigurationForm(instance=config, rclone_remotes=rclone_remotes)

    remote_name, remote_folder = split_remote_path(config.remote_path)

    return render(request, 'checklists/backups.html', {
        'form': form,
        'config': config,
        'runtime': runtime,
        'remote_name': remote_name,
        'remote_folder': remote_folder,
        'backup_rows': list_local_backups(),
        'remote_backup_rows': list_remote_backups(config),
        'upload_form': upload_form,
        'remote_examples': [
            ('Google Drive', 'gdrive:MyRobotBackups/checklist'),
            ('OneDrive', 'onedrive:MyRobotBackups/checklist'),
        ],
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def templates_list(request):
    status = request.GET.get('status', 'ativas')
    position_id = request.GET.get('cargo')
    positions = Position.objects.all().order_by('-active', 'name')
    templates = TaskTemplate.objects.select_related('position').order_by('position__name', 'day_of_week', 'start_time', 'order', 'title')
    if status == 'inativas':
        templates = templates.filter(active=False)
    elif status != 'todas':
        status = 'ativas'
        templates = templates.filter(active=True)
    if position_id and position_id.isdigit():
        templates = templates.filter(position_id=position_id)

    pending_suggestions = ActivitySuggestion.objects.filter(
        status=ActivitySuggestion.STATUS_PENDING,
    ).select_related('position', 'requested_by', 'target_template').order_by('created_at')

    return render(request, 'checklists/templates_list.html', {
        'templates': templates,
        'positions': positions,
        'pending_suggestions': pending_suggestions,
        'status': status,
        'position_id': position_id or '',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def template_create(request):
    if request.method == 'POST':
        form = TaskTemplateForm(request.POST)
        if form.is_valid():
            template = form.save()
            log_activity(
                actor=request.user,
                obj=template,
                action='Atividade criada',
                object_label=template.title,
                details=f'Atividade: {template.title}; cargo: {template.position.name}; ativa: {template.active}',
                new_values=snapshot_instance(template, TASK_TEMPLATE_AUDIT_FIELDS),
            )
            messages.success(request, 'Atividade criada.')
            return redirect('templates_list')
    else:
        form = TaskTemplateForm()

    return render(request, 'checklists/template_form.html', {
        'form': form,
        'title': 'Cadastrar atividade',
        'submit_label': 'Cadastrar atividade',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def template_edit(request, template_id):
    template = get_object_or_404(TaskTemplate.objects.select_related('position'), pk=template_id)
    previous_active = template.active
    previous_values_full = snapshot_instance(template, TASK_TEMPLATE_AUDIT_FIELDS)
    if request.method == 'POST':
        form = TaskTemplateForm(request.POST, instance=template)
        if form.is_valid():
            template = form.save()
            previous_values, new_values = changed_values(
                previous_values_full,
                snapshot_instance(template, TASK_TEMPLATE_AUDIT_FIELDS),
            )
            if previous_active and not template.active:
                action = 'Atividade inativada'
            elif not previous_active and template.active:
                action = 'Atividade reativada'
            else:
                action = 'Atividade atualizada'
            log_activity(
                actor=request.user,
                obj=template,
                action=action,
                object_label=template.title,
                details=f'Atividade: {template.title}; cargo: {template.position.name}; ativa: {template.active}',
                previous_values=previous_values,
                new_values=new_values,
            )
            messages.success(request, 'Atividade atualizada.')
            return redirect('templates_list')
    else:
        form = TaskTemplateForm(instance=template)

    return render(request, 'checklists/template_form.html', {
        'form': form,
        'title': f'Editar atividade - {template.title}',
        'submit_label': 'Salvar alterações',
        'template_obj': template,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def template_import(request):
    errors_by_row = []
    if request.method == 'POST':
        uploaded_file = request.FILES.get('arquivo')
        if not uploaded_file:
            errors_by_row = [{'row': 'Arquivo', 'errors': ['Selecione um arquivo XLSX para importar.']}]
        elif not uploaded_file.name.lower().endswith('.xlsx'):
            errors_by_row = [{'row': 'Arquivo', 'errors': ['Envie um arquivo no formato .xlsx.']}]
        else:
            rows, errors_by_row = parse_activity_import(uploaded_file)
            if not errors_by_row:
                result = import_activity_rows(rows, request.user, uploaded_file.name)
                messages.success(
                    request,
                    f'Importação concluída: {result.created} atividade(s) criada(s) e {result.updated} atualizada(s).',
                )
                return redirect('templates_list')

    return render(request, 'checklists/template_import.html', {
        'errors_by_row': errors_by_row,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def template_import_model(request):
    output = build_activity_import_template()
    response = HttpResponse(
        output.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="modelo_importacao_atividades.xlsx"'
    return response


@user_passes_test(_admin_check)
def activity_suggestion_review(request, suggestion_id):
    suggestion = get_object_or_404(
        ActivitySuggestion.objects.select_related('position', 'requested_by', 'target_template', 'created_template'),
        pk=suggestion_id,
    )

    if suggestion.request_type == ActivitySuggestion.TYPE_CREATE:
        return _review_activity_creation_suggestion(request, suggestion)
    return _review_activity_deactivation_suggestion(request, suggestion)


def _mark_suggestion_rejected(request, suggestion, review_note=''):
    with transaction.atomic():
        previous_values_full = snapshot_instance(suggestion, ACTIVITY_SUGGESTION_AUDIT_FIELDS)
        suggestion.status = ActivitySuggestion.STATUS_REJECTED
        suggestion.review_note = review_note.strip()
        suggestion.reviewed_by = request.user
        suggestion.reviewed_at = timezone.now()
        suggestion.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at', 'updated_at'])
        previous_values, new_values = changed_values(
            previous_values_full,
            snapshot_instance(suggestion, ACTIVITY_SUGGESTION_AUDIT_FIELDS),
        )
        log_activity(
            actor=request.user,
            obj=suggestion,
            position=suggestion.position,
            action='Sugestão de atividade rejeitada',
            object_label=suggestion.title or (suggestion.target_template.title if suggestion.target_template_id else ''),
            details=f'Tipo: {suggestion.get_request_type_display()}; solicitante: {suggestion.requested_by.username}',
            previous_values=previous_values,
            new_values=new_values,
        )


def _review_activity_creation_suggestion(request, suggestion):
    if request.method == 'POST':
        action = request.POST.get('action')
        if not suggestion.is_pending:
            messages.error(request, 'Esta sugestão já foi revisada.')
            return redirect('templates_list')
        if action == 'reject':
            _mark_suggestion_rejected(request, suggestion, request.POST.get('review_note', ''))
            messages.success(request, 'Sugestão rejeitada. Nenhuma atividade foi criada.')
            return redirect('templates_list')

        form = ActivitySuggestionReviewForm(request.POST, instance=suggestion)
        if form.is_valid():
            with transaction.atomic():
                suggestion_before = snapshot_instance(suggestion, ACTIVITY_SUGGESTION_AUDIT_FIELDS)
                suggestion = form.save(commit=False)
                template = TaskTemplate.objects.create(
                    position=suggestion.position,
                    day_of_week=suggestion.day_of_week,
                    start_time=suggestion.start_time,
                    end_time=suggestion.end_time,
                    title=suggestion.title,
                    expected_result=suggestion.expected_result,
                    frequency=suggestion.frequency,
                    requires_evidence=suggestion.requires_evidence,
                    evidence_required=suggestion.evidence_required,
                    proof_location=suggestion.proof_location,
                    notes=suggestion.notes,
                    source='Sugestão operacional',
                    active=True,
                )
                suggestion.status = ActivitySuggestion.STATUS_APPROVED
                suggestion.created_template = template
                suggestion.reviewed_by = request.user
                suggestion.reviewed_at = timezone.now()
                suggestion.save()
                log_activity(
                    actor=request.user,
                    obj=template,
                    action='Atividade criada por sugestão',
                    object_label=template.title,
                    details=f'Atividade: {template.title}; sugestão: {suggestion.id}; solicitante: {suggestion.requested_by.username}',
                    new_values=snapshot_instance(template, TASK_TEMPLATE_AUDIT_FIELDS),
                )
                suggestion_previous_values, suggestion_new_values = changed_values(
                    suggestion_before,
                    snapshot_instance(suggestion, ACTIVITY_SUGGESTION_AUDIT_FIELDS),
                )
                log_activity(
                    actor=request.user,
                    obj=suggestion,
                    position=template.position,
                    action='Sugestão de atividade aprovada',
                    object_label=suggestion.title,
                    details=f'Atividade criada: {template.id} - {template.title}',
                    previous_values=suggestion_previous_values,
                    new_values=suggestion_new_values,
                )
            messages.success(request, 'Sugestão aprovada e atividade criada.')
            return redirect('templates_list')
    else:
        form = ActivitySuggestionReviewForm(instance=suggestion)

    return render(request, 'checklists/activity_suggestion_review.html', {
        'suggestion': suggestion,
        'form': form,
        'is_admin': True,
    })


def _review_activity_deactivation_suggestion(request, suggestion):
    if request.method == 'POST':
        action = request.POST.get('action')
        if not suggestion.is_pending:
            messages.error(request, 'Esta sugestão já foi revisada.')
            return redirect('templates_list')
        if action == 'reject':
            _mark_suggestion_rejected(request, suggestion, request.POST.get('review_note', ''))
            messages.success(request, 'Sugestão rejeitada. Nenhuma atividade foi inativada.')
            return redirect('templates_list')
        if action == 'approve':
            with transaction.atomic():
                target = suggestion.target_template
                target_before = snapshot_instance(target, TASK_TEMPLATE_AUDIT_FIELDS) if target else {}
                suggestion_before = snapshot_instance(suggestion, ACTIVITY_SUGGESTION_AUDIT_FIELDS)
                if target and target.active:
                    target.active = False
                    target.save(update_fields=['active'])
                suggestion.status = ActivitySuggestion.STATUS_APPROVED
                suggestion.review_note = request.POST.get('review_note', '').strip()
                suggestion.reviewed_by = request.user
                suggestion.reviewed_at = timezone.now()
                suggestion.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at', 'updated_at'])
                target_previous_values, target_new_values = changed_values(
                    target_before,
                    snapshot_instance(target, TASK_TEMPLATE_AUDIT_FIELDS) if target else {},
                )
                log_activity(
                    actor=request.user,
                    obj=target,
                    position=suggestion.position,
                    action='Atividade inativada por sugestão',
                    object_type='TaskTemplate',
                    object_id=str(target.id if target else ''),
                    object_label=target.title if target else '',
                    details=f'Atividade: {target.title if target else "-"}; sugestão: {suggestion.id}; solicitante: {suggestion.requested_by.username}',
                    previous_values=target_previous_values,
                    new_values=target_new_values,
                )
                suggestion_previous_values, suggestion_new_values = changed_values(
                    suggestion_before,
                    snapshot_instance(suggestion, ACTIVITY_SUGGESTION_AUDIT_FIELDS),
                )
                log_activity(
                    actor=request.user,
                    obj=suggestion,
                    position=suggestion.position,
                    action='Sugestão de atividade aprovada',
                    object_label=target.title if target else '',
                    details=f'Atividade inativada: {target.id if target else "-"} - {target.title if target else "-"}',
                    previous_values=suggestion_previous_values,
                    new_values=suggestion_new_values,
                )
            messages.success(request, 'Sugestão aprovada e atividade inativada.')
            return redirect('templates_list')

    return render(request, 'checklists/activity_suggestion_review.html', {
        'suggestion': suggestion,
        'form': None,
        'is_admin': True,
    })


@login_required
def metrics(request):
    positions = visible_positions(request.user)
    position = _selected_position(request)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado.')
    metric_period, reference_date = _parse_metric_period(request)
    dashboard_user = None if is_admin_user(request.user) else request.user

    if request.method == 'POST':
        if not is_admin_user(request.user):
            return HttpResponseForbidden('Usuário comum não pode registrar indicadores.')
        form = MetricRecordForm(request.POST, request.FILES)
        applicable_metrics = (
            MetricType.objects.filter(active=True)
            .filter(Q(position=position) | Q(position__isnull=True))
            .select_related('activity', 'position')
            .order_by('area', 'name')
        )
        form.fields['metric'].queryset = applicable_metrics
        if form.is_valid():
            obj = form.save(commit=False)
            obj.position = position
            obj.executor_full_name = _current_employee_name(request.user)
            obj.created_by = request.user
            obj.save()
            log_activity(
                actor=request.user,
                obj=obj,
                position=position,
                action='Indicador registrado',
                object_label=f'{obj.metric.name} - {obj.date}',
                details=f'Responsável: {obj.executor_full_name}',
                new_values=snapshot_instance(obj, METRIC_RECORD_AUDIT_FIELDS),
            )
            messages.success(request, 'Indicador registrado.')
            return redirect(f'{request.path}?cargo={position.id}&periodo={metric_period}&data={reference_date.isoformat()}')
    else:
        form = MetricRecordForm(initial={'date': timezone.localdate()})
        applicable_metrics = (
            MetricType.objects.filter(active=True)
            .filter(Q(position=position) | Q(position__isnull=True))
            .select_related('activity', 'position')
            .order_by('area', 'name')
        )
        form.fields['metric'].queryset = applicable_metrics

    records = MetricRecord.objects.filter(position=position).select_related('metric', 'metric__activity').order_by('-date', '-created_at')[:100]
    metric_dashboard = metric_dashboard_data(metric_period, reference_date, [position], user=dashboard_user)
    return render(request, 'checklists/metrics.html', {
        'position': position,
        'positions': positions,
        'form': form,
        'applicable_metrics': applicable_metrics,
        'period_choices': METRIC_PERIOD_CHOICES,
        'metric_period': metric_dashboard['period'],
        'reference_date': reference_date,
        'metric_dashboard': metric_dashboard,
        'records': records,
        'is_admin': is_admin_user(request.user),
    })


@user_passes_test(_admin_check)
def metric_types_list(request):
    status = request.GET.get('status', 'ativos')
    position_id = request.GET.get('cargo')
    positions = Position.objects.all().order_by('-active', 'name')
    metrics = MetricType.objects.select_related('position', 'activity').order_by('position__name', 'area', 'name')
    if status == 'inativos':
        metrics = metrics.filter(active=False)
    elif status != 'todos':
        status = 'ativos'
        metrics = metrics.filter(active=True)
    if position_id and position_id.isdigit():
        metrics = metrics.filter(position_id=position_id)

    return render(request, 'checklists/metric_types_list.html', {
        'metrics': metrics,
        'positions': positions,
        'status': status,
        'position_id': position_id or '',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def metric_type_create(request):
    if request.method == 'POST':
        form = MetricTypeForm(request.POST)
        if form.is_valid():
            metric = form.save()
            log_activity(
                actor=request.user,
                obj=metric,
                action='Indicador criado',
                object_label=metric.name,
                details=f'Indicador: {metric.name}; área: {metric.area}; ativo: {metric.active}',
                new_values=snapshot_instance(metric, METRIC_TYPE_AUDIT_FIELDS),
            )
            messages.success(request, 'Indicador criado.')
            return redirect('metric_types_list')
    else:
        form = MetricTypeForm()

    activities = TaskTemplate.objects.select_related('position').filter(active=True).order_by('position__name', 'day_of_week', 'start_time', 'title')
    return render(request, 'checklists/metric_type_form.html', {
        'form': form,
        'activities': activities,
        'selected_activity_id': str(form['activity'].value() or ''),
        'selected_position_id': str(form['position'].value() or ''),
        'title': 'Cadastrar indicador',
        'submit_label': 'Cadastrar indicador',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def metric_type_edit(request, metric_id):
    metric = get_object_or_404(MetricType.objects.select_related('position', 'activity'), pk=metric_id)
    previous_active = metric.active
    previous_values_full = snapshot_instance(metric, METRIC_TYPE_AUDIT_FIELDS)
    if request.method == 'POST':
        form = MetricTypeForm(request.POST, instance=metric)
        if form.is_valid():
            metric = form.save()
            previous_values, new_values = changed_values(
                previous_values_full,
                snapshot_instance(metric, METRIC_TYPE_AUDIT_FIELDS),
            )
            if previous_active and not metric.active:
                action = 'Indicador inativado'
            elif not previous_active and metric.active:
                action = 'Indicador reativado'
            else:
                action = 'Indicador atualizado'
            log_activity(
                actor=request.user,
                obj=metric,
                action=action,
                object_label=metric.name,
                details=f'Indicador: {metric.name}; área: {metric.area}; ativo: {metric.active}',
                previous_values=previous_values,
                new_values=new_values,
            )
            messages.success(request, 'Indicador atualizado.')
            return redirect('metric_types_list')
    else:
        form = MetricTypeForm(instance=metric)

    activities = TaskTemplate.objects.select_related('position').order_by('position__name', 'day_of_week', 'start_time', 'title')
    return render(request, 'checklists/metric_type_form.html', {
        'form': form,
        'activities': activities,
        'selected_activity_id': str(form['activity'].value() or ''),
        'selected_position_id': str(form['position'].value() or ''),
        'title': f'Editar indicador - {metric.name}',
        'submit_label': 'Salvar alterações',
        'metric_obj': metric,
        'is_admin': True,
    })


@login_required
def metric_evidence_download(request, record_id):
    record = get_object_or_404(MetricRecord.objects.select_related('position'), pk=record_id)
    if record.position not in visible_positions(request.user):
        return HttpResponseForbidden('Você não pode acessar esta evidência.')
    if not record.evidence_file:
        raise Http404('Arquivo não encontrado.')
    return FileResponse(record.evidence_file.open('rb'), as_attachment=False, filename=record.evidence_file.name.split('/')[-1])


@login_required
def evidence_attachment_download(request, attachment_id):
    attachment = get_object_or_404(EvidenceAttachment.objects.select_related('occurrence__position'), pk=attachment_id)
    if not _can_access_position_history(request.user, attachment.occurrence.position):
        return HttpResponseForbidden('Você não pode acessar esta evidência.')
    if not attachment.file:
        raise Http404('Arquivo não encontrado.')
    return FileResponse(attachment.file.open('rb'), as_attachment=True, filename=attachment.original_name or attachment.file.name.split('/')[-1])


@login_required
def legacy_evidence_download(request, occurrence_id):
    occurrence = get_object_or_404(ChecklistOccurrence.objects.select_related('position'), pk=occurrence_id)
    if not _can_access_position_history(request.user, occurrence.position):
        return HttpResponseForbidden('Você não pode acessar esta evidência.')
    if not occurrence.evidence_file:
        raise Http404('Arquivo não encontrado.')
    return FileResponse(occurrence.evidence_file.open('rb'), as_attachment=True, filename=occurrence.evidence_file.name.split('/')[-1])


@login_required
def monthly_csv(request):
    year, month = _parse_month_year(request)
    positions = visible_positions(request.user)
    start, end = month_range(year, month)
    qs = ChecklistOccurrence.objects.filter(date__range=(start, end), position__in=positions).select_related('position', 'template').order_by('date', 'position__name', 'template__order')
    qs = filter_absence_ignored_occurrences(qs)
    return _occurrences_csv_response(qs, f'relatorio_checklist_{year}_{month:02d}.csv')


@login_required
def history_csv(request):
    positions = _history_positions_for_user(request.user)
    qs = ChecklistOccurrence.objects.filter(position__in=positions).select_related('position', 'template').prefetch_related('attachments').order_by('-date', 'position__name')
    qs = filter_absence_ignored_occurrences(qs)
    return _occurrences_csv_response(qs, 'historico_checklist.csv')


def _occurrences_csv_response(qs, filename):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Data', 'Cargo', 'Tarefa', 'Status', 'Funcionário', 'Evidência textual', 'Anexos', 'Pendência/Bloqueio', 'Atualizado por', 'Atualizado em'])
    for item in qs:
        writer.writerow([
            item.date.isoformat(),
            item.position.name,
            item.template.title,
            item.operational_status_label,
            item.executor_full_name,
            item.evidence_text,
            '; '.join([a.original_name or a.file.name for a in item.attachments.all()]),
            item.blocked_reason,
            item.updated_by.username if item.updated_by else '',
            timezone.localtime(item.updated_at).strftime('%d/%m/%Y %H:%M'),
        ])
    return response


@user_passes_test(_admin_check)
def employees_list(request):
    profiles = UserProfile.objects.select_related('user', 'position').order_by('system_role', 'display_name')
    return render(request, 'checklists/employees_list.html', {
        'profiles': profiles,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            ActivityLog.objects.create(
                actor=request.user,
                position=user.userprofile.position,
                action='Usuário cadastrado com senha temporária',
                object_type='User',
                object_id=str(user.id),
                details=f'Usuário: {user.userprofile.display_name}; perfil: {user.userprofile.get_system_role_display()}',
            )
            return render(request, 'checklists/temporary_password.html', {
                'title': 'Usuário cadastrado',
                'user_obj': user,
                'temporary_password': form.generated_password,
                'force_password_change': user.userprofile.must_change_password,
                'is_admin': True,
            })
    else:
        form = EmployeeCreateForm()
    return render(request, 'checklists/employee_form.html', {
        'form': form,
        'title': 'Cadastrar usuário',
        'submit_label': 'Cadastrar e gerar senha temporária',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def employee_edit(request, user_id):
    user_obj = get_object_or_404(User.objects.select_related('userprofile'), pk=user_id)
    profile = user_obj.userprofile
    initial = {
        'full_name': profile.display_name,
        'username': user_obj.username,
        'email': user_obj.email,
        'role': _role_initial(profile),
        'active': user_obj.is_active and profile.active,
    }
    if request.method == 'POST':
        form = EmployeeUpdateForm(request.POST, user_obj=user_obj)
        if form.is_valid():
            user_obj = form.save()
            ActivityLog.objects.create(
                actor=request.user,
                position=user_obj.userprofile.position,
                action='Usuário atualizado',
                object_type='User',
                object_id=str(user_obj.id),
                details=f'Usuário: {user_obj.userprofile.display_name}; perfil: {user_obj.userprofile.get_system_role_display()}',
            )
            messages.success(request, 'Usuário atualizado.')
            return redirect('employees_list')
    else:
        form = EmployeeUpdateForm(initial=initial, user_obj=user_obj)
    return render(request, 'checklists/employee_form.html', {
        'form': form,
        'title': f'Editar usuário — {profile.display_name}',
        'submit_label': 'Salvar alterações',
        'employee_user': user_obj,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def employee_reset_password(request, user_id):
    user_obj = get_object_or_404(User.objects.select_related('userprofile'), pk=user_id)
    if request.method == 'POST':
        form = AdminPasswordResetForm(request.POST, user_obj=user_obj)
        if form.is_valid():
            form.save()
            ActivityLog.objects.create(
                actor=request.user,
                position=user_obj.userprofile.position,
                action='Senha temporária de usuário gerada',
                object_type='User',
                object_id=str(user_obj.id),
                details=f'Usuário: {user_obj.userprofile.display_name}',
            )
            return render(request, 'checklists/temporary_password.html', {
                'title': 'Senha temporária gerada',
                'user_obj': user_obj,
                'temporary_password': form.generated_password,
                'force_password_change': user_obj.userprofile.must_change_password,
                'is_admin': True,
            })
    else:
        form = AdminPasswordResetForm(user_obj=user_obj)
    return render(request, 'checklists/employee_form.html', {
        'form': form,
        'title': f'Gerar nova senha temporária — {user_obj.userprofile.display_name}',
        'submit_label': 'Gerar senha temporária',
        'employee_user': user_obj,
        'is_admin': True,
    })
