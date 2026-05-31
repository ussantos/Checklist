import csv
from datetime import datetime, timedelta
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.db.models import F, Q
from .forms import (
    AdminPasswordResetForm, DailyNoteForm, EmployeeCreateForm, EmployeeUpdateForm,
    MetricRecordForm, MetricTypeForm, OccurrenceUpdateForm, TaskTemplateForm,
)
from .models import (
    ActivityLog, ChecklistOccurrence, ChecklistOccurrenceStatusEvent, DailyNote,
    EvidenceAttachment, MetricRecord, MetricType, Position, TaskTemplate, UserProfile,
)
from .activity_import import (
    build_activity_import_template, import_activity_rows, parse_activity_import,
)
from .services import (
    absence_for_user_on_date, create_due_occurrences, create_occurrences_for_positions,
    filter_absence_ignored_occurrences, get_user_position, is_admin_user, metrics_summary,
    month_range, monthly_summary, overdue_occurrences, position_absences_on_date,
    position_is_fully_absent_on_date, status_duration_summary, user_is_absent_on_date,
    visible_positions, working_days_between,
)

User = get_user_model()


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


def _parse_month_year(request):
    today = timezone.localdate()
    year = int(request.GET.get('ano', today.year))
    month = int(request.GET.get('mes', today.month))
    return year, month


def _selected_position(request):
    positions = visible_positions(request.user)
    pos_id = request.GET.get('cargo')
    if pos_id and is_admin_user(request.user):
        return get_object_or_404(positions, pk=pos_id)
    return positions.first()


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
        return redirect('activities')

    today = timezone.localdate()
    year, month = _parse_month_year(request)
    positions = visible_positions(request.user)

    create_occurrences_for_positions(positions, today)

    summary = monthly_summary(year, month, positions)
    overdue = overdue_occurrences(positions, limit=20)
    metric_rows = metrics_summary(year, month, positions)
    recent_candidates = ChecklistOccurrence.objects.filter(position__in=positions).select_related('position', 'template').order_by('-updated_at')[:80]
    recent = filter_absence_ignored_occurrences(recent_candidates)[:20]

    return render(request, 'checklists/dashboard.html', {
        'today': today,
        'year': year,
        'month': month,
        'positions': positions,
        'summary': summary,
        'metric_rows': metric_rows,
        'overdue': overdue,
        'recent': recent,
        'is_admin': is_admin_user(request.user),
    })


@login_required
def activities(request):
    if is_admin_user(request.user):
        return redirect('dashboard')

    position = get_user_position(request.user)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado. Peça ao administrador para configurar o perfil.')

    period = request.GET.get('periodo', 'dia')
    if period not in {'dia', 'semana', 'mes'}:
        period = 'dia'

    reference_date = _parse_date(request.GET.get('data'))
    if period == 'semana':
        start_date = reference_date - timedelta(days=reference_date.weekday())
        end_date = start_date + timedelta(days=4)
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
    for day in days:
        absence = absences_by_day.get(day)
        grouped.append((day, [] if absence else [item for item in occurrences if item.date == day], absence))

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
        'position': position,
        'grouped': grouped,
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
    allowed = occurrence.position in visible_positions(request.user)
    if not allowed:
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
    if occurrence.position not in visible_positions(request.user):
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
    positions = visible_positions(request.user)
    qs = ChecklistOccurrence.objects.filter(position__in=positions).select_related('position', 'template')

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
        'is_admin': is_admin_user(request.user),
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

    return render(request, 'checklists/templates_list.html', {
        'templates': templates,
        'positions': positions,
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
            ActivityLog.objects.create(
                actor=request.user,
                position=template.position,
                action='Atividade criada',
                object_type='TaskTemplate',
                object_id=str(template.id),
                details=f'Atividade: {template.title}; cargo: {template.position.name}; ativa: {template.active}',
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
    if request.method == 'POST':
        form = TaskTemplateForm(request.POST, instance=template)
        if form.is_valid():
            template = form.save()
            if previous_active and not template.active:
                action = 'Atividade inativada'
            elif not previous_active and template.active:
                action = 'Atividade reativada'
            else:
                action = 'Atividade atualizada'
            ActivityLog.objects.create(
                actor=request.user,
                position=template.position,
                action=action,
                object_type='TaskTemplate',
                object_id=str(template.id),
                details=f'Atividade: {template.title}; cargo: {template.position.name}; ativa: {template.active}',
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


@login_required
def metrics(request):
    positions = visible_positions(request.user)
    position = _selected_position(request)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado.')

    if request.method == 'POST':
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
            ActivityLog.objects.create(actor=request.user, position=position, action='Indicador registrado', object_type='MetricRecord', object_id=str(obj.id), details=f'Responsável: {obj.executor_full_name}')
            messages.success(request, 'Indicador registrado.')
            return redirect(f'{request.path}?cargo={position.id}')
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
    return render(request, 'checklists/metrics.html', {
        'position': position,
        'positions': positions,
        'form': form,
        'applicable_metrics': applicable_metrics,
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
            ActivityLog.objects.create(
                actor=request.user,
                position=metric.position,
                action='Indicador criado',
                object_type='MetricType',
                object_id=str(metric.id),
                details=f'Indicador: {metric.name}; área: {metric.area}; ativo: {metric.active}',
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
    if request.method == 'POST':
        form = MetricTypeForm(request.POST, instance=metric)
        if form.is_valid():
            metric = form.save()
            if previous_active and not metric.active:
                action = 'Indicador inativado'
            elif not previous_active and metric.active:
                action = 'Indicador reativado'
            else:
                action = 'Indicador atualizado'
            ActivityLog.objects.create(
                actor=request.user,
                position=metric.position,
                action=action,
                object_type='MetricType',
                object_id=str(metric.id),
                details=f'Indicador: {metric.name}; área: {metric.area}; ativo: {metric.active}',
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
    if attachment.occurrence.position not in visible_positions(request.user):
        return HttpResponseForbidden('Você não pode acessar esta evidência.')
    if not attachment.file:
        raise Http404('Arquivo não encontrado.')
    return FileResponse(attachment.file.open('rb'), as_attachment=False, filename=attachment.original_name or attachment.file.name)


@login_required
def legacy_evidence_download(request, occurrence_id):
    occurrence = get_object_or_404(ChecklistOccurrence.objects.select_related('position'), pk=occurrence_id)
    if occurrence.position not in visible_positions(request.user):
        return HttpResponseForbidden('Você não pode acessar esta evidência.')
    if not occurrence.evidence_file:
        raise Http404('Arquivo não encontrado.')
    return FileResponse(occurrence.evidence_file.open('rb'), as_attachment=False, filename=occurrence.evidence_file.name.split('/')[-1])


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
    positions = visible_positions(request.user)
    qs = ChecklistOccurrence.objects.filter(position__in=positions).select_related('position', 'template').order_by('-date', 'position__name')
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
