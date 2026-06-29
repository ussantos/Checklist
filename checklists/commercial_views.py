from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .audit import changed_values, log_activity, snapshot_instance
from .forms import (
    CommercialFunnelForm, CommercialOpportunityForm, FunnelModelFieldFormSet,
    FunnelModelForm, FunnelStageForm, FunnelTypeForm, OpportunityOriginForm,
)
from .models import (
    CommercialFunnel, CommercialOpportunity, CommercialOpportunityFollowUp,
    FunnelModel, FunnelModelField, FunnelStage, FunnelType, OpportunityOrigin,
)
from .services import is_admin_user


FUNNEL_TYPE_AUDIT_FIELDS = ['name', 'code', 'active']
FUNNEL_STAGE_AUDIT_FIELDS = ['name', 'code', 'description', 'order', 'active']
OPPORTUNITY_ORIGIN_AUDIT_FIELDS = ['name', 'code', 'description', 'active']
FUNNEL_MODEL_AUDIT_FIELDS = ['name', 'active']
COMMERCIAL_FUNNEL_AUDIT_FIELDS = ['name', 'funnel_model', 'active']
COMMERCIAL_OPPORTUNITY_AUDIT_FIELDS = [
    'title', 'commercial_funnel', 'funnel_type', 'stage', 'origin', 'contact_name', 'contact_phone',
    'next_follow_up_date', 'field_values', 'notes', 'active',
]


def _admin_check(user):
    return user.is_authenticated and is_admin_user(user)


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


def _record_follow_up_event(*, opportunity, actor, previous_date=None, note=''):
    return CommercialOpportunityFollowUp.objects.create(
        opportunity=opportunity,
        previous_date=previous_date,
        scheduled_date=opportunity.next_follow_up_date,
        note=(note or '').strip(),
        actor=actor,
    )


def _confirm_delete(request, *, title, object_label, warning, cancel_url):
    return render(request, 'checklists/commercial_confirm_delete.html', {
        'title': title,
        'object_label': object_label,
        'warning': warning,
        'cancel_url': cancel_url,
        'is_admin': True,
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


@user_passes_test(_admin_check)
def commercial_opportunities_list(request):
    status = request.GET.get('status', 'ativos')
    funnel_type_id = request.GET.get('tipo', '')
    stage_id = request.GET.get('etapa', '')
    funnel_id = request.GET.get('funil', '')
    opportunities = (
        _commercial_opportunity_queryset()
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
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def commercial_opportunity_create(request):
    if request.method == 'POST':
        form = CommercialOpportunityForm(request.POST)
        if form.is_valid():
            opportunity = form.save()
            opportunity = _commercial_opportunity_queryset().get(pk=opportunity.pk)
            _record_follow_up_event(
                opportunity=opportunity,
                actor=request.user,
                previous_date=None,
                note=form.cleaned_data.get('follow_up_note') or 'Follow-up inicial da oportunidade.',
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
            return redirect('commercial_opportunities')
    else:
        initial = {}
        funnel_id = request.GET.get('funil')
        if funnel_id and funnel_id.isdigit():
            initial['commercial_funnel'] = funnel_id
        form = CommercialOpportunityForm(initial=initial)

    return render(request, 'checklists/commercial_opportunity_form.html', {
        'form': form,
        'title': 'Criar oportunidade',
        'submit_label': 'Criar oportunidade',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def commercial_opportunity_edit(request, opportunity_id):
    opportunity = get_object_or_404(_commercial_opportunity_queryset(), pk=opportunity_id)
    previous_active = opportunity.active
    previous_follow_up_date = opportunity.next_follow_up_date
    previous_values_full = _commercial_opportunity_snapshot(opportunity)
    if request.method == 'POST':
        form = CommercialOpportunityForm(request.POST, instance=opportunity)
        if form.is_valid():
            opportunity = form.save()
            opportunity = _commercial_opportunity_queryset().get(pk=opportunity.pk)
            follow_up_note = form.cleaned_data.get('follow_up_note') or ''
            if previous_follow_up_date != opportunity.next_follow_up_date or follow_up_note.strip():
                _record_follow_up_event(
                    opportunity=opportunity,
                    actor=request.user,
                    previous_date=previous_follow_up_date,
                    note=follow_up_note,
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
            return redirect('commercial_opportunities')
    else:
        form = CommercialOpportunityForm(instance=opportunity)

    return render(request, 'checklists/commercial_opportunity_form.html', {
        'form': form,
        'title': f'Editar oportunidade - {opportunity.title}',
        'submit_label': 'Salvar alterações',
        'opportunity': opportunity,
        'follow_up_events': opportunity.follow_up_events.select_related('actor')[:20],
        'is_admin': True,
    })


@require_POST
@user_passes_test(_admin_check)
def commercial_opportunity_toggle(request, opportunity_id):
    opportunity = get_object_or_404(_commercial_opportunity_queryset(), pk=opportunity_id)
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
    return redirect('commercial_opportunities')


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
