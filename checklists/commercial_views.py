from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .audit import changed_values, log_activity, snapshot_instance
from .forms import FunnelTypeForm
from .models import FunnelType
from .services import is_admin_user


FUNNEL_TYPE_AUDIT_FIELDS = ['name', 'code', 'active']


def _admin_check(user):
    return user.is_authenticated and is_admin_user(user)


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
