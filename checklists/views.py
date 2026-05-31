import csv
from datetime import datetime, timedelta
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db.models import Q
from .forms import (
    AdminPasswordResetForm, DailyNoteForm, EmployeeCreateForm, EmployeeUpdateForm,
    MetricRecordForm, OccurrenceUpdateForm,
)
from .models import (
    ActivityLog, ChecklistOccurrence, DailyNote, EvidenceAttachment, MetricRecord,
    MetricType, Position, TaskTemplate, UserProfile,
)
from .services import (
    create_due_occurrences, create_occurrences_for_positions, get_user_position,
    is_admin_user, metrics_summary, month_range, monthly_summary,
    overdue_occurrences, visible_positions,
)

User = get_user_model()


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
    mesmo que o nome do funcionário seja alterado posteriormente.
    """
    profile = getattr(user, 'userprofile', None)
    if profile and profile.display_name:
        return profile.display_name
    full = user.get_full_name().strip()
    return full or user.username


def _admin_check(user):
    return user.is_authenticated and is_admin_user(user)


@login_required
def dashboard(request):
    today = timezone.localdate()
    year, month = _parse_month_year(request)
    positions = visible_positions(request.user)

    # Gera as tarefas do dia para que o dashboard mostre o estado atual.
    create_occurrences_for_positions(positions, today)

    summary = monthly_summary(year, month, positions)
    overdue = overdue_occurrences(positions, limit=20)
    metric_rows = metrics_summary(year, month, positions)
    recent = ChecklistOccurrence.objects.filter(position__in=positions).select_related('position', 'template').order_by('-updated_at')[:20]

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
def checklist_day(request):
    target_date = _parse_date(request.GET.get('data'))
    position = _selected_position(request)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado. Peça ao administrador para configurar o perfil.')

    create_due_occurrences(position, target_date)
    occurrences = ChecklistOccurrence.objects.filter(position=position, date=target_date).select_related('template').order_by('template__order', 'template__start_time', 'template__title')
    note, _ = DailyNote.objects.get_or_create(position=position, date=target_date)

    if request.method == 'POST' and request.POST.get('form_type') == 'daily_note':
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
        'statuses': ChecklistOccurrence.STATUS_CHOICES,
        'employee_name': _current_employee_name(request.user),
        'note_form': form,
        'is_admin': is_admin_user(request.user),
    })


@login_required
def week_view(request):
    selected = _parse_date(request.GET.get('data'))
    monday = selected - timedelta(days=selected.weekday())
    days = [monday + timedelta(days=i) for i in range(5)]
    position = _selected_position(request)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado.')

    for day in days:
        create_due_occurrences(position, day)

    grouped = []
    for day in days:
        items = ChecklistOccurrence.objects.filter(position=position, date=day).select_related('template').order_by('template__order', 'template__start_time')
        grouped.append((day, items))

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

    old_status = occurrence.status
    has_existing = bool(occurrence.evidence_file) or occurrence.attachments.exists()
    form = OccurrenceUpdateForm(request.POST, request.FILES, instance=occurrence, has_existing_file=has_existing)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.executor_full_name = _current_employee_name(request.user)
        obj.mark_status(form.cleaned_data['status'], request.user)
        obj.save()
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
        messages.success(request, 'Tarefa atualizada.')
    else:
        messages.error(request, 'Não foi possível salvar. Verifique os campos.')
    return redirect(request.META.get('HTTP_REFERER', 'checklist_day'))


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

    qs = qs.order_by('-date', 'position__name', 'template__order')[:800]
    return render(request, 'checklists/history.html', {
        'occurrences': qs,
        'positions': positions,
        'statuses': ChecklistOccurrence.STATUS_CHOICES,
        'is_admin': is_admin_user(request.user),
    })


@login_required
def templates_list(request):
    positions = visible_positions(request.user)
    templates = TaskTemplate.objects.filter(position__in=positions).select_related('position').order_by('position__name', 'day_of_week', 'order')
    return render(request, 'checklists/templates_list.html', {
        'templates': templates,
        'positions': positions,
        'is_admin': is_admin_user(request.user),
    })


@login_required
def metrics(request):
    positions = visible_positions(request.user)
    position = _selected_position(request)
    if not position:
        return HttpResponseForbidden('Usuário sem cargo vinculado.')

    if request.method == 'POST':
        form = MetricRecordForm(request.POST, request.FILES)
        form.fields['metric'].queryset = MetricType.objects.filter(active=True, position__in=[position]) | MetricType.objects.filter(active=True, position__isnull=True)
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
        form.fields['metric'].queryset = MetricType.objects.filter(active=True, position__in=[position]) | MetricType.objects.filter(active=True, position__isnull=True)

    records = MetricRecord.objects.filter(position=position).select_related('metric').order_by('-date', '-created_at')[:100]
    return render(request, 'checklists/metrics.html', {
        'position': position,
        'positions': positions,
        'form': form,
        'records': records,
        'is_admin': is_admin_user(request.user),
    })


@login_required
def evidence_attachment_download(request, attachment_id):
    """Entrega anexo de evidência somente para usuário autorizado.

    Como as evidências podem conter dados pessoais, os arquivos não são
    servidos publicamente pela URL /media/. O usuário precisa estar logado e
    ter acesso ao cargo da ocorrência.
    """
    attachment = get_object_or_404(
        EvidenceAttachment.objects.select_related('occurrence__position'),
        pk=attachment_id,
    )
    if attachment.occurrence.position not in visible_positions(request.user):
        return HttpResponseForbidden('Você não pode acessar esta evidência.')
    if not attachment.file:
        raise Http404('Arquivo não encontrado.')
    return FileResponse(attachment.file.open('rb'), as_attachment=False, filename=attachment.original_name or attachment.file.name)


@login_required
def legacy_evidence_download(request, occurrence_id):
    """Entrega o arquivo legado de uma ocorrência, se existir."""
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
    return _occurrences_csv_response(qs, f'relatorio_checklist_{year}_{month:02d}.csv')


@login_required
def history_csv(request):
    positions = visible_positions(request.user)
    qs = ChecklistOccurrence.objects.filter(position__in=positions).select_related('position', 'template').order_by('-date', 'position__name')
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
            item.get_status_display(),
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
    profiles = UserProfile.objects.filter(system_role=UserProfile.ROLE_OPERATOR).select_related('user', 'position').order_by('display_name')
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
            ActivityLog.objects.create(actor=request.user, position=user.userprofile.position, action='Funcionário cadastrado', object_type='User', object_id=str(user.id), details=f'Funcionário: {user.userprofile.display_name}')
            messages.success(request, 'Funcionário cadastrado com sucesso.')
            return redirect('employees_list')
    else:
        form = EmployeeCreateForm()
    return render(request, 'checklists/employee_form.html', {
        'form': form,
        'title': 'Cadastrar funcionário',
        'submit_label': 'Cadastrar',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def employee_edit(request, user_id):
    user_obj = get_object_or_404(User.objects.select_related('userprofile'), pk=user_id, userprofile__system_role=UserProfile.ROLE_OPERATOR)
    profile = user_obj.userprofile
    initial = {
        'full_name': profile.display_name,
        'username': user_obj.username,
        'email': user_obj.email,
        'position': profile.position,
        'active': user_obj.is_active and profile.active,
    }
    if request.method == 'POST':
        form = EmployeeUpdateForm(request.POST, user_obj=user_obj)
        if form.is_valid():
            user_obj = form.save()
            ActivityLog.objects.create(actor=request.user, position=user_obj.userprofile.position, action='Funcionário atualizado', object_type='User', object_id=str(user_obj.id), details=f'Funcionário: {user_obj.userprofile.display_name}')
            messages.success(request, 'Funcionário atualizado.')
            return redirect('employees_list')
    else:
        form = EmployeeUpdateForm(initial=initial, user_obj=user_obj)
    return render(request, 'checklists/employee_form.html', {
        'form': form,
        'title': f'Editar funcionário — {profile.display_name}',
        'submit_label': 'Salvar alterações',
        'employee_user': user_obj,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def employee_reset_password(request, user_id):
    user_obj = get_object_or_404(User.objects.select_related('userprofile'), pk=user_id, userprofile__system_role=UserProfile.ROLE_OPERATOR)
    if request.method == 'POST':
        form = AdminPasswordResetForm(request.POST, user_obj=user_obj)
        if form.is_valid():
            form.save()
            ActivityLog.objects.create(actor=request.user, position=user_obj.userprofile.position, action='Senha de funcionário redefinida', object_type='User', object_id=str(user_obj.id), details=f'Funcionário: {user_obj.userprofile.display_name}')
            messages.success(request, 'Senha redefinida com sucesso.')
            return redirect('employees_list')
    else:
        form = AdminPasswordResetForm(user_obj=user_obj)
    return render(request, 'checklists/employee_form.html', {
        'form': form,
        'title': f'Redefinir senha — {user_obj.userprofile.display_name}',
        'submit_label': 'Redefinir senha',
        'employee_user': user_obj,
        'is_admin': True,
    })
