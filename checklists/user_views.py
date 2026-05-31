from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AdminPasswordResetForm, EmployeeAbsenceForm, EmployeeCreateForm, EmployeeUpdateForm, PositionForm
from .models import ActivityLog, EmployeeAbsence, Position, UserProfile
from .services import is_admin_user

User = get_user_model()


def _admin_check(user):
    return user.is_authenticated and is_admin_user(user)


def _role_initial(profile):
    if profile.system_role == UserProfile.ROLE_ADMIN:
        return 'ADMIN'
    if profile.position_id:
        return f'POSITION:{profile.position_id}'
    return ''


@user_passes_test(_admin_check)
def users_list(request):
    profiles = UserProfile.objects.select_related('user', 'position').order_by('system_role', 'display_name')
    return render(request, 'checklists/employees_list.html', {
        'profiles': profiles,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def positions_list(request):
    status = request.GET.get('status', 'ativos')
    positions = Position.objects.all().order_by('-active', 'name')
    if status == 'inativos':
        positions = positions.filter(active=False)
    elif status != 'todos':
        status = 'ativos'
        positions = positions.filter(active=True)

    return render(request, 'checklists/positions_list.html', {
        'positions': positions,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def absences_list(request):
    status = request.GET.get('status', 'ativas')
    profile_id = request.GET.get('colaborador')
    absences = EmployeeAbsence.objects.select_related('profile', 'profile__user', 'profile__position').order_by('-start_date')
    if status == 'inativas':
        absences = absences.filter(active=False)
    elif status != 'todas':
        status = 'ativas'
        absences = absences.filter(active=True)
    if profile_id and profile_id.isdigit():
        absences = absences.filter(profile_id=profile_id)

    profiles = UserProfile.objects.select_related('position', 'user').filter(
        system_role=UserProfile.ROLE_OPERATOR,
        position__isnull=False,
    ).order_by('display_name')
    return render(request, 'checklists/absences_list.html', {
        'absences': absences,
        'profiles': profiles,
        'status': status,
        'profile_id': profile_id or '',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def absence_create(request, user_id=None):
    initial = {}
    if user_id:
        profile = get_object_or_404(
            UserProfile.objects.select_related('user', 'position'),
            user_id=user_id,
            system_role=UserProfile.ROLE_OPERATOR,
            position__isnull=False,
        )
        initial['profile'] = profile
    if request.method == 'POST':
        form = EmployeeAbsenceForm(request.POST)
        if form.is_valid():
            absence = form.save(commit=False)
            absence.created_by = request.user
            absence.save()
            ActivityLog.objects.create(
                actor=request.user,
                position=absence.profile.position,
                action='Ausência de colaborador registrada',
                object_type='EmployeeAbsence',
                object_id=str(absence.id),
                details=f'Colaborador: {absence.profile.display_name}; período: {absence.start_date} a {absence.end_date}; tipo: {absence.get_absence_type_display()}',
            )
            messages.success(request, 'Ausência registrada.')
            return redirect('absences_list')
    else:
        form = EmployeeAbsenceForm(initial=initial)

    return render(request, 'checklists/absence_form.html', {
        'form': form,
        'title': 'Registrar ausência',
        'submit_label': 'Registrar ausência',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def absence_edit(request, absence_id):
    absence = get_object_or_404(EmployeeAbsence.objects.select_related('profile', 'profile__position'), pk=absence_id)
    was_active = absence.active
    if request.method == 'POST':
        form = EmployeeAbsenceForm(request.POST, instance=absence)
        if form.is_valid():
            absence = form.save()
            if was_active and not absence.active:
                action = 'Ausência de colaborador cancelada'
            elif not was_active and absence.active:
                action = 'Ausência de colaborador reativada'
            else:
                action = 'Ausência de colaborador atualizada'
            ActivityLog.objects.create(
                actor=request.user,
                position=absence.profile.position,
                action=action,
                object_type='EmployeeAbsence',
                object_id=str(absence.id),
                details=f'Colaborador: {absence.profile.display_name}; período: {absence.start_date} a {absence.end_date}; tipo: {absence.get_absence_type_display()}',
            )
            messages.success(request, 'Ausência atualizada.')
            return redirect('absences_list')
    else:
        form = EmployeeAbsenceForm(instance=absence)

    return render(request, 'checklists/absence_form.html', {
        'form': form,
        'title': f'Editar ausência - {absence.profile.display_name}',
        'submit_label': 'Salvar alterações',
        'absence': absence,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def position_create(request):
    if request.method == 'POST':
        form = PositionForm(request.POST)
        if form.is_valid():
            position = form.save()
            ActivityLog.objects.create(
                actor=request.user,
                position=position,
                action='Tipo de usuário comum criado',
                object_type='Position',
                object_id=str(position.id),
                details=f'Cargo: {position.name}; código: {position.code}; ativo: {position.active}',
            )
            messages.success(request, 'Tipo/cargo criado.')
            return redirect('positions_list')
    else:
        form = PositionForm()

    return render(request, 'checklists/position_form.html', {
        'form': form,
        'title': 'Cadastrar tipo/cargo',
        'submit_label': 'Cadastrar tipo/cargo',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def position_edit(request, position_id):
    position = get_object_or_404(Position, pk=position_id)
    previous_active = position.active
    if request.method == 'POST':
        form = PositionForm(request.POST, instance=position)
        if form.is_valid():
            position = form.save()
            if previous_active and not position.active:
                action = 'Tipo de usuário comum inativado'
            elif not previous_active and position.active:
                action = 'Tipo de usuário comum reativado'
            else:
                action = 'Tipo de usuário comum atualizado'
            ActivityLog.objects.create(
                actor=request.user,
                position=position,
                action=action,
                object_type='Position',
                object_id=str(position.id),
                details=f'Cargo: {position.name}; código: {position.code}; ativo: {position.active}',
            )
            messages.success(request, 'Tipo/cargo atualizado.')
            return redirect('positions_list')
    else:
        form = PositionForm(instance=position)

    return render(request, 'checklists/position_form.html', {
        'form': form,
        'title': f'Editar tipo/cargo - {position.name}',
        'submit_label': 'Salvar alterações',
        'position_obj': position,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def user_create(request):
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
def user_edit(request, user_id):
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
def user_reset_password(request, user_id):
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
