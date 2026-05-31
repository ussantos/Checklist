from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AdminPasswordResetForm, EmployeeCreateForm, EmployeeUpdateForm
from .models import ActivityLog, UserProfile
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
