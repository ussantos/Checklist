import json
from calendar import monthrange
from datetime import datetime, timedelta
from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet
from django.forms.formsets import DELETION_FIELD_NAME
from django.utils import timezone
from django.utils.text import slugify
from .backup import build_remote_path, split_remote_path
from .models import (
    ActivitySuggestion, BackupConfiguration, ChecklistOccurrence, CommercialFunnel,
    CommercialOpportunity, Course, DailyNote, EmployeeAbsence, FunnelModel,
    FunnelModelField, FunnelStage, FunnelType, Lesson, LessonFeedback, MetricRecord, MetricType,
    OpportunityOrigin, PedagogicalStudent, Position, Room, SchoolHoliday,
    TaskTemplate, TimeSlot, UserProfile,
)
from .security import generate_temporary_password, should_force_password_change_on_first_login


User = get_user_model()


def add_months(value, months):
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def is_lost_stage(stage):
    return bool(stage and 'perdido' in slugify(f'{stage.code} {stage.name}'))


class OccurrenceUpdateForm(forms.ModelForm):
    """Formulário para registrar a execução de uma atividade."""

    class Meta:
        model = ChecklistOccurrence
        fields = ['status', 'evidence_text', 'blocked_reason']
        widgets = {
            'status': forms.Select(attrs={'class': 'input'}),
            'evidence_text': forms.Textarea(attrs={'class': 'input', 'rows': 3, 'placeholder': 'Descreva a evidência objetiva da execução. Ex.: lead registrado, print anexado, e-mail enviado, aula registrada.'}),
            'blocked_reason': forms.Textarea(attrs={'class': 'input', 'rows': 2, 'placeholder': 'Obrigatório se a tarefa ficar pendente/bloqueada.'}),
        }

    def __init__(self, *args, **kwargs):
        self.requires_evidence = kwargs.pop('requires_evidence', True)
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = ChecklistOccurrence.OPERATIONAL_STATUS_CHOICES
        self.fields['blocked_reason'].label = 'Observação operacional'
        self.fields['blocked_reason'].widget.attrs['placeholder'] = 'Obrigatório quando a atividade estiver atrasada.'
        if not self.requires_evidence:
            self.fields.pop('evidence_text', None)

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get('status')
        evidence_text = (cleaned.get('evidence_text') or '').strip()
        blocked_reason = (cleaned.get('blocked_reason') or '').strip()

        if self.requires_evidence and status == ChecklistOccurrence.STATUS_DONE and not evidence_text:
            raise forms.ValidationError('Para concluir uma atividade, registre evidência textual.')
        if status == ChecklistOccurrence.STATUS_BLOCKED and not blocked_reason:
            raise forms.ValidationError('Informe a observação operacional quando a atividade estiver atrasada.')
        return cleaned


class DailyNoteForm(forms.ModelForm):
    class Meta:
        model = DailyNote
        fields = ['notes']
        widgets = {
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 4, 'placeholder': 'Resumo do dia: ocorrências, pendências, pontos de atenção e decisões.'}),
        }


class MetricRecordForm(forms.ModelForm):
    class Meta:
        model = MetricRecord
        fields = ['metric', 'date', 'value', 'notes']
        widgets = {
            'metric': forms.Select(attrs={'class': 'input'}),
            'date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'value': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 3}),
        }
        labels = {
            'metric': 'Indicador',
            'date': 'Data',
            'value': 'Valor',
            'notes': 'Observações',
        }


class MetricTypeForm(forms.ModelForm):
    name = forms.CharField(
        label='Nome do indicador',
        max_length=140,
        widget=forms.TextInput(attrs={'class': 'input'}),
    )
    area = forms.CharField(
        label='Área',
        max_length=70,
        widget=forms.TextInput(attrs={'class': 'input', 'maxlength': 70}),
    )

    class Meta:
        model = MetricType
        fields = ['name', 'area', 'frequency', 'position', 'activity', 'monthly_target', 'unit', 'active']
        widgets = {
            'frequency': forms.Select(attrs={'class': 'input'}),
            'position': forms.Select(attrs={'class': 'input'}),
            'activity': forms.Select(attrs={'class': 'input'}),
            'monthly_target': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'unit': forms.TextInput(attrs={'class': 'input'}),
            'active': forms.CheckboxInput(),
        }
        labels = {
            'frequency': 'Frequência',
            'position': 'Aplica-se ao',
            'activity': 'Atividade',
            'monthly_target': 'Meta',
            'unit': 'Unidade',
            'active': 'Ativo',
        }
        help_texts = {
            'activity': 'Opcional. Selecione uma atividade do tipo/cargo escolhido.',
            'active': 'Desmarque para inativar sem apagar histórico.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        positions = Position.objects.filter(active=True).order_by('name')
        if self.instance and self.instance.pk and self.instance.position_id:
            positions = Position.objects.filter(
                pk__in=list(positions.values_list('pk', flat=True)) + [self.instance.position_id]
            ).order_by('name')
        self.fields['position'].queryset = positions
        self.fields['position'].required = True

        activities = TaskTemplate.objects.select_related('position').order_by('position__name', 'day_of_week', 'start_time', 'title')
        if not self.instance.pk:
            activities = activities.filter(active=True)
        self.fields['activity'].queryset = activities
        self.fields['activity'].required = False
        self.fields['active'].initial = True

    def clean(self):
        cleaned = super().clean()
        position = cleaned.get('position')
        activity = cleaned.get('activity')
        if activity and position and activity.position_id != position.id:
            raise forms.ValidationError('A atividade selecionada deve pertencer ao tipo/cargo do indicador.')
        return cleaned

    def _unique_code(self, metric):
        position_code = metric.position.code if metric.position_id else 'geral'
        base = slugify(f'{position_code}-{metric.area}-{metric.name}')[:70] or 'indicador'
        code = base
        suffix = 2
        qs = MetricType.objects.all()
        if metric.pk:
            qs = qs.exclude(pk=metric.pk)
        while qs.filter(code=code).exists():
            suffix_text = f'-{suffix}'
            code = f'{base[:80 - len(suffix_text)]}{suffix_text}'
            suffix += 1
        return code

    def save(self, commit=True):
        metric = super().save(commit=False)
        if not metric.code:
            metric.code = self._unique_code(metric)
        if commit:
            metric.save()
        return metric


class PositionForm(forms.ModelForm):
    code = forms.SlugField(
        label='Código/slug',
        max_length=80,
        help_text='Use um identificador curto, sem espaços. Ex.: atendente-comercial.',
        widget=forms.TextInput(attrs={'class': 'input'}),
    )

    class Meta:
        model = Position
        fields = ['name', 'code', 'description', 'active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'class': 'input', 'rows': 4}),
            'active': forms.CheckboxInput(),
        }
        labels = {
            'name': 'Nome do tipo/cargo',
            'description': 'Descrição',
            'active': 'Ativo',
        }

    def clean_code(self):
        code = slugify(self.cleaned_data['code'])
        if not code:
            raise forms.ValidationError('Informe um código válido.')
        qs = Position.objects.filter(code=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe um tipo/cargo com este código.')
        return code


class FunnelTypeForm(forms.ModelForm):
    code = forms.CharField(
        label='Código/slug',
        max_length=80,
        required=False,
        help_text='Opcional. Se ficar em branco, será gerado a partir do nome.',
        widget=forms.TextInput(attrs={'class': 'input'}),
    )

    class Meta:
        model = FunnelType
        fields = ['name', 'code', 'active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'active': forms.CheckboxInput(),
        }
        labels = {
            'name': 'Nome do tipo de funil',
            'active': 'Ativo',
        }
        help_texts = {
            'active': 'Desmarque para impedir uso em novos funis sem apagar o tipo.',
        }

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise forms.ValidationError('Informe o nome do tipo de funil.')
        qs = FunnelType.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe um tipo de funil com este nome.')
        return name

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get('name') or ''
        code = slugify(cleaned.get('code') or name)
        if not code:
            raise forms.ValidationError('Informe um nome ou código válido.')
        qs = FunnelType.objects.filter(code=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe um tipo de funil com este código.')
        cleaned['code'] = code
        return cleaned


class FunnelStageForm(forms.ModelForm):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativado'),
        (STATUS_INACTIVE, 'Desativado'),
    ]

    status = forms.ChoiceField(
        label='Status',
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'input'}),
    )

    class Meta:
        model = FunnelStage
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
        }
        labels = {
            'name': 'Nome da etapa',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].initial = self.STATUS_ACTIVE if self.instance.active else self.STATUS_INACTIVE

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise forms.ValidationError('Informe o nome da etapa.')
        qs = FunnelStage.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe uma etapa com este nome.')
        return name

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get('name') or ''
        code = slugify(name)
        if not code:
            raise forms.ValidationError('Informe um nome válido.')
        qs = FunnelStage.objects.filter(code=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe uma etapa com nome equivalente.')
        cleaned['code'] = code
        return cleaned

    def save(self, commit=True):
        stage = super().save(commit=False)
        stage.code = self.cleaned_data['code']
        stage.active = self.cleaned_data.get('status') == self.STATUS_ACTIVE
        if commit:
            stage.save()
        return stage


class OpportunityOriginForm(forms.ModelForm):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativado'),
        (STATUS_INACTIVE, 'Desativado'),
    ]

    status = forms.ChoiceField(
        label='Status',
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'input'}),
    )

    class Meta:
        model = OpportunityOrigin
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
        }
        labels = {
            'name': 'Nome da origem',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].initial = self.STATUS_ACTIVE if self.instance.active else self.STATUS_INACTIVE

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise forms.ValidationError('Informe o nome da origem.')
        qs = OpportunityOrigin.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe uma origem com este nome.')
        return name

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get('name') or ''
        code = slugify(name)
        if not code:
            raise forms.ValidationError('Informe um nome válido.')
        qs = OpportunityOrigin.objects.filter(code=code)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe uma origem com nome equivalente.')
        cleaned['code'] = code
        return cleaned

    def save(self, commit=True):
        origin = super().save(commit=False)
        origin.code = self.cleaned_data['code']
        origin.active = self.cleaned_data.get('status') == self.STATUS_ACTIVE
        if commit:
            origin.save()
        return origin


class FunnelModelForm(forms.ModelForm):
    class Meta:
        model = FunnelModel
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
        }
        labels = {
            'name': 'Nome do modelo',
        }

    def clean_name(self):
        value = (self.cleaned_data.get('name') or '').strip()
        if not value:
            raise forms.ValidationError('Informe o nome do modelo.')
        return value


class FunnelModelFieldForm(forms.ModelForm):
    options_text = forms.CharField(
        label='Opções da caixa de seleção',
        required=False,
        help_text='Informe uma opção por linha. Obrigatório apenas para Caixa de Seleção.',
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3}),
    )

    class Meta:
        model = FunnelModelField
        fields = ['name', 'field_type', 'required', 'options_text', 'order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'field_type': forms.Select(attrs={'class': 'input'}),
            'required': forms.CheckboxInput(),
            'order': forms.NumberInput(attrs={'class': 'input small', 'min': 0}),
        }
        labels = {
            'name': 'Nome do campo',
            'field_type': 'Tipo do campo',
            'required': 'Obrigatório',
            'order': 'Ordem',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.options:
            self.fields['options_text'].initial = '\n'.join(self.instance.options)

    def clean_name(self):
        value = (self.cleaned_data.get('name') or '').strip()
        if not value:
            raise forms.ValidationError('Informe o nome do campo.')
        return value

    def clean(self):
        cleaned = super().clean()
        field_type = cleaned.get('field_type')
        options_text = cleaned.get('options_text') or ''
        options = [line.strip() for line in options_text.splitlines() if line.strip()]
        if field_type == FunnelModelField.TYPE_SELECT and not options:
            raise forms.ValidationError('Informe pelo menos uma opção para campos do tipo Caixa de Seleção.')
        cleaned['options'] = options if field_type == FunnelModelField.TYPE_SELECT else []
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.options = self.cleaned_data.get('options', [])
        if commit:
            obj.save()
        return obj


class BaseFunnelModelFieldFormSet(BaseInlineFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.field_in_use = False
        if not form.instance or not form.instance.pk:
            return
        if not form.instance.has_opportunity_usage():
            return
        form.field_in_use = True
        delete_field = form.fields.get(DELETION_FIELD_NAME)
        if delete_field:
            delete_field.disabled = True
            delete_field.help_text = 'Este campo ja esta vinculado a oportunidades e nao pode ser removido.'

    def clean(self):
        super().clean()
        names = set()
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if form.cleaned_data.get('DELETE'):
                if form.instance and form.instance.pk and form.instance.has_opportunity_usage():
                    form.add_error(
                        DELETION_FIELD_NAME,
                        'Este campo nao pode ser removido porque o modelo ja possui oportunidades vinculadas.',
                    )
                    raise forms.ValidationError('Campos adicionais ja usados por oportunidades nao podem ser removidos.')
                continue
            name = form.cleaned_data.get('name')
            if not name:
                continue
            key = name.casefold()
            if key in names:
                raise forms.ValidationError('Não repita nomes de campos adicionais no mesmo modelo de funil.')
            names.add(key)


FunnelModelFieldFormSet = inlineformset_factory(
    FunnelModel,
    FunnelModelField,
    form=FunnelModelFieldForm,
    formset=BaseFunnelModelFieldFormSet,
    extra=1,
    can_delete=True,
)


class CommercialFunnelForm(forms.ModelForm):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativado'),
        (STATUS_INACTIVE, 'Desativado'),
    ]

    status = forms.ChoiceField(
        label='Status',
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'input'}),
    )

    class Meta:
        model = CommercialFunnel
        fields = ['name', 'funnel_model']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'funnel_model': forms.Select(attrs={'class': 'input'}),
        }
        labels = {
            'name': 'Nome do funil',
            'funnel_model': 'Modelo de funil',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].initial = self.STATUS_ACTIVE if self.instance.active else self.STATUS_INACTIVE
        models = (
            FunnelModel.objects.filter(active=True)
            .order_by('name')
        )
        if self.instance and self.instance.pk and self.instance.funnel_model_id:
            models = (
                FunnelModel.objects.filter(
                    pk__in=list(models.values_list('pk', flat=True)) + [self.instance.funnel_model_id]
                )
                .order_by('name')
            )
        self.fields['funnel_model'].queryset = models

    def clean_name(self):
        value = (self.cleaned_data.get('name') or '').strip()
        if not value:
            raise forms.ValidationError('Informe o nome do funil.')
        qs = CommercialFunnel.objects.filter(name__iexact=value)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe um funil com este nome.')
        return value

    def save(self, commit=True):
        funnel = super().save(commit=False)
        funnel.active = self.cleaned_data.get('status') == self.STATUS_ACTIVE
        if commit:
            funnel.save()
        return funnel


class CourseForm(forms.ModelForm):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativo'),
        (STATUS_INACTIVE, 'Desativado'),
    ]

    status = forms.ChoiceField(
        label='Status',
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'input'}),
    )

    class Meta:
        model = Course
        fields = ['name', 'description', 'value', 'kit_quantity', 'max_students_per_slot']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'description': forms.Textarea(attrs={'class': 'input', 'rows': 3}),
            'value': forms.NumberInput(attrs={'class': 'input', 'min': '0', 'step': '0.01'}),
            'kit_quantity': forms.NumberInput(attrs={'class': 'input', 'min': '1'}),
            'max_students_per_slot': forms.NumberInput(attrs={'class': 'input', 'min': '1'}),
        }
        labels = {
            'name': 'Nome',
            'description': 'Descrição',
            'value': 'Valor',
            'kit_quantity': 'Quantidade de kits',
            'max_students_per_slot': 'Máximo de alunos por horário',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].initial = self.STATUS_ACTIVE if self.instance.active else self.STATUS_INACTIVE

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise forms.ValidationError('Informe o nome do curso.')
        if self.instance and self.instance.pk and name == (self.instance.name or '').strip():
            return name
        qs = Course.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe um curso com este nome.')
        return name

    def clean_value(self):
        value = self.cleaned_data.get('value')
        if value is None:
            raise forms.ValidationError('Informe o valor do curso.')
        if value < 0:
            raise forms.ValidationError('O valor do curso não pode ser negativo.')
        return value

    def clean_kit_quantity(self):
        value = self.cleaned_data.get('kit_quantity')
        if not value or value < 1:
            raise forms.ValidationError('Informe ao menos 1 kit disponível.')
        return value

    def clean_max_students_per_slot(self):
        value = self.cleaned_data.get('max_students_per_slot')
        if value is not None and value < 1:
            raise forms.ValidationError('Informe um número maior que zero ou deixe em branco.')
        return value

    def save(self, commit=True):
        course = super().save(commit=False)
        course.active = self.cleaned_data.get('status') == self.STATUS_ACTIVE
        if commit:
            course.save()
        return course


class RoomForm(forms.ModelForm):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativa'),
        (STATUS_INACTIVE, 'Desativada'),
    ]

    status = forms.ChoiceField(label='Status', choices=STATUS_CHOICES, widget=forms.Select(attrs={'class': 'input'}))

    class Meta:
        model = Room
        fields = ['name', 'capacity']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'capacity': forms.NumberInput(attrs={'class': 'input', 'min': '1'}),
        }
        labels = {
            'name': 'Nome',
            'capacity': 'Capacidade',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].initial = self.STATUS_ACTIVE if self.instance.active else self.STATUS_INACTIVE

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise forms.ValidationError('Informe o nome da sala.')
        qs = Room.objects.filter(name__iexact=name)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe uma sala com este nome.')
        return name

    def clean_capacity(self):
        value = self.cleaned_data.get('capacity')
        if not value or value < 1:
            raise forms.ValidationError('Informe capacidade maior que zero.')
        return value

    def save(self, commit=True):
        room = super().save(commit=False)
        room.active = self.cleaned_data.get('status') == self.STATUS_ACTIVE
        if commit:
            room.save()
        return room


class TimeSlotForm(forms.ModelForm):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativo'),
        (STATUS_INACTIVE, 'Desativado'),
    ]

    status = forms.ChoiceField(label='Status', choices=STATUS_CHOICES, widget=forms.Select(attrs={'class': 'input'}))

    class Meta:
        model = TimeSlot
        fields = ['weekday', 'start_time', 'end_time']
        widgets = {
            'weekday': forms.Select(attrs={'class': 'input'}),
            'start_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
        }
        labels = {
            'weekday': 'Dia da semana',
            'start_time': 'Início',
            'end_time': 'Fim',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].initial = self.STATUS_ACTIVE if self.instance.active else self.STATUS_INACTIVE

    def clean(self):
        cleaned = super().clean()
        start_time = cleaned.get('start_time')
        end_time = cleaned.get('end_time')
        weekday = cleaned.get('weekday')
        if start_time and end_time:
            if start_time >= end_time:
                raise forms.ValidationError('A hora fim deve ser maior que a hora de início.')
            duration = (
                datetime.combine(datetime.today(), end_time)
                - datetime.combine(datetime.today(), start_time)
            ).total_seconds() / 3600
            if duration > 2:
                raise forms.ValidationError('Horários pedagógicos podem durar no máximo 2 horas.')
        if weekday is not None and start_time and end_time:
            qs = TimeSlot.objects.filter(weekday=weekday, start_time=start_time, end_time=end_time)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('Já existe este horário para o dia selecionado.')
        return cleaned

    def save(self, commit=True):
        slot = super().save(commit=False)
        slot.active = self.cleaned_data.get('status') == self.STATUS_ACTIVE
        if commit:
            slot.save()
        return slot


class SchoolHolidayForm(forms.ModelForm):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativo'),
        (STATUS_INACTIVE, 'Desativado'),
    ]

    status = forms.ChoiceField(label='Status', choices=STATUS_CHOICES, widget=forms.Select(attrs={'class': 'input'}))

    class Meta:
        model = SchoolHoliday
        fields = ['description', 'kind', 'start_date', 'end_date']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'input'}),
            'kind': forms.Select(attrs={'class': 'input'}),
            'start_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
        }
        labels = {
            'description': 'Descrição',
            'kind': 'Tipo',
            'start_date': 'Data inicial',
            'end_date': 'Data final',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].initial = self.STATUS_ACTIVE if self.instance.active else self.STATUS_INACTIVE

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError('A data final deve ser igual ou posterior à data inicial.')
        return cleaned

    def save(self, commit=True):
        holiday = super().save(commit=False)
        holiday.active = self.cleaned_data.get('status') == self.STATUS_ACTIVE
        if commit:
            holiday.save()
        return holiday


class PedagogicalStudentForm(forms.ModelForm):
    class Meta:
        model = PedagogicalStudent
        fields = ['name', 'enrollment_number', 'responsible_name', 'whatsapp', 'status', 'source', 'external_id']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input'}),
            'enrollment_number': forms.TextInput(attrs={'class': 'input'}),
            'responsible_name': forms.TextInput(attrs={'class': 'input'}),
            'whatsapp': forms.TextInput(attrs={'class': 'input'}),
            'status': forms.Select(attrs={'class': 'input'}),
            'source': forms.TextInput(attrs={'class': 'input'}),
            'external_id': forms.TextInput(attrs={'class': 'input'}),
        }
        labels = {
            'name': 'Nome',
            'enrollment_number': 'Matrícula',
            'responsible_name': 'Responsável',
            'whatsapp': 'WhatsApp',
            'status': 'Status',
            'source': 'Origem',
            'external_id': 'ID externo',
        }

    def clean_name(self):
        value = (self.cleaned_data.get('name') or '').strip()
        if not value:
            raise forms.ValidationError('Informe o nome do aluno.')
        return value

    def clean_enrollment_number(self):
        value = (self.cleaned_data.get('enrollment_number') or '').strip()
        if value:
            qs = PedagogicalStudent.objects.filter(enrollment_number__iexact=value)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('Já existe um aluno com esta matrícula.')
        return value


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = [
            'lesson_type', 'trial_kind', 'commercial_opportunity',
            'student', 'student_name_snapshot', 'responsible_name_snapshot',
            'whatsapp_snapshot', 'course', 'room', 'date', 'start_time', 'end_time',
            'status', 'notes',
        ]
        widgets = {
            'lesson_type': forms.Select(attrs={'class': 'input'}),
            'trial_kind': forms.Select(attrs={'class': 'input'}),
            'commercial_opportunity': forms.Select(attrs={'class': 'input'}),
            'student': forms.Select(attrs={'class': 'input'}),
            'student_name_snapshot': forms.TextInput(attrs={'class': 'input'}),
            'responsible_name_snapshot': forms.TextInput(attrs={'class': 'input'}),
            'whatsapp_snapshot': forms.TextInput(attrs={'class': 'input'}),
            'course': forms.Select(attrs={'class': 'input'}),
            'room': forms.Select(attrs={'class': 'input'}),
            'date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
            'status': forms.Select(attrs={'class': 'input'}),
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 4}),
        }
        labels = {
            'lesson_type': 'Tipo',
            'trial_kind': 'Experimental ou Play',
            'commercial_opportunity': 'Oportunidade',
            'student': 'Aluno matriculado',
            'student_name_snapshot': 'Nome do interessado',
            'responsible_name_snapshot': 'Responsável',
            'whatsapp_snapshot': 'WhatsApp',
            'course': 'Curso',
            'room': 'Sala',
            'date': 'Data',
            'start_time': 'Início',
            'end_time': 'Fim',
            'status': 'Status',
            'notes': 'Observação',
        }

    def __init__(self, *args, **kwargs):
        self.trial_only = kwargs.pop('trial_only', False)
        super().__init__(*args, **kwargs)
        if self.trial_only:
            self.fields['lesson_type'].initial = Lesson.TYPE_TRIAL
            self.fields['lesson_type'].widget = forms.HiddenInput()
            self.fields['student'].widget = forms.HiddenInput()
        courses = Course.objects.filter(active=True).order_by('name')
        rooms = Room.objects.filter(active=True).order_by('name')
        students = PedagogicalStudent.objects.filter(status=PedagogicalStudent.STATUS_ACTIVE).order_by('name')
        opportunities = CommercialOpportunity.objects.filter(active=True).order_by('title')
        if self.instance and self.instance.pk:
            if self.instance.course_id:
                courses = Course.objects.filter(pk__in=list(courses.values_list('pk', flat=True)) + [self.instance.course_id]).order_by('name')
            if self.instance.room_id:
                rooms = Room.objects.filter(pk__in=list(rooms.values_list('pk', flat=True)) + [self.instance.room_id]).order_by('name')
            if self.instance.student_id:
                students = PedagogicalStudent.objects.filter(pk__in=list(students.values_list('pk', flat=True)) + [self.instance.student_id]).order_by('name')
            if self.instance.commercial_opportunity_id:
                opportunities = CommercialOpportunity.objects.filter(pk__in=list(opportunities.values_list('pk', flat=True)) + [self.instance.commercial_opportunity_id]).order_by('title')
        self.fields['course'].queryset = courses
        self.fields['room'].queryset = rooms
        self.fields['student'].queryset = students
        self.fields['commercial_opportunity'].queryset = opportunities
        self.fields['student'].required = False
        self.fields['student_name_snapshot'].required = False
        self.fields['responsible_name_snapshot'].required = False
        self.fields['whatsapp_snapshot'].required = False
        self.fields['course'].required = not self.trial_only
        self.fields['notes'].required = False
        self.fields['commercial_opportunity'].required = self.trial_only
        self.fields['trial_kind'].required = self.trial_only
        if self.trial_only and not self.fields['trial_kind'].initial and not self.initial.get('trial_kind'):
            self.fields['trial_kind'].initial = Lesson.TRIAL_KIND_EXPERIMENTAL

    def clean(self):
        cleaned = super().clean()
        if self.trial_only:
            cleaned['lesson_type'] = Lesson.TYPE_TRIAL
        lesson_type = cleaned.get('lesson_type')
        student = cleaned.get('student')
        opportunity = cleaned.get('commercial_opportunity')
        trial_kind = cleaned.get('trial_kind')
        course = cleaned.get('course')
        student_name = (cleaned.get('student_name_snapshot') or '').strip()
        if lesson_type == Lesson.TYPE_REGULAR and not student:
            self.add_error('student', 'Selecione um aluno para aula de matriculado.')
        if lesson_type == Lesson.TYPE_REGULAR and not course:
            self.add_error('course', 'Selecione um curso para aula de matriculado.')
        if lesson_type == Lesson.TYPE_TRIAL:
            if not trial_kind:
                self.add_error('trial_kind', 'Informe se a aula é Experimental ou Play.')
            if not opportunity:
                self.add_error('commercial_opportunity', 'Vincule a aula a uma oportunidade comercial.')
            if not student_name and not opportunity:
                self.add_error('student_name_snapshot', 'Informe o nome do interessado.')
        return cleaned


class LessonFeedbackForm(forms.ModelForm):
    NOTE_CHOICES = [('', 'Selecione')] + [(score, str(score)) for score in range(0, 11)]

    class Meta:
        model = LessonFeedback
        fields = [
            'module_number',
            'lesson_number',
            'punctuality_score',
            'assembly_comment',
            'assembly_score',
            'has_programming',
            'programming_comment',
            'programming_score',
            'participation_comment',
            'participation_score',
            'behavior_comment',
            'behavior_score',
            'general_comment',
            'general_score',
        ]
        widgets = {
            'module_number': forms.Select(attrs={'class': 'input'}),
            'lesson_number': forms.Select(attrs={'class': 'input'}),
            'punctuality_score': forms.Select(attrs={'class': 'input', 'data-feedback-score': '1'}),
            'assembly_comment': forms.Textarea(attrs={'class': 'input', 'rows': 4}),
            'assembly_score': forms.Select(attrs={'class': 'input', 'data-feedback-score': '1'}),
            'has_programming': forms.CheckboxInput(attrs={'data-programming-toggle': '1'}),
            'programming_comment': forms.Textarea(attrs={'class': 'input', 'rows': 4, 'data-programming-field': '1'}),
            'programming_score': forms.Select(attrs={'class': 'input', 'data-feedback-score': '1', 'data-programming-field': '1'}),
            'participation_comment': forms.Textarea(attrs={'class': 'input', 'rows': 4}),
            'participation_score': forms.Select(attrs={'class': 'input', 'data-feedback-score': '1'}),
            'behavior_comment': forms.Textarea(attrs={'class': 'input', 'rows': 4}),
            'behavior_score': forms.Select(attrs={'class': 'input', 'data-feedback-score': '1'}),
            'general_comment': forms.Textarea(attrs={'class': 'input', 'rows': 5}),
            'general_score': forms.NumberInput(attrs={'class': 'input', 'readonly': 'readonly', 'data-general-score': '1'}),
        }
        labels = {
            'module_number': 'Módulo',
            'lesson_number': 'Aula',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['module_number'].choices = [('', 'Selecione'), *LessonFeedback.MODULE_CHOICES]
        self.fields['lesson_number'].choices = [('', 'Selecione'), *LessonFeedback.LESSON_NUMBER_CHOICES]
        for field_name in ['assembly_score', 'programming_score', 'participation_score', 'behavior_score']:
            self.fields[field_name].choices = self.NOTE_CHOICES
        self.fields['punctuality_score'].choices = [('', 'Selecione'), *LessonFeedback.PUNCTUALITY_CHOICES]
        self.fields['general_score'].required = False
        self.fields['general_score'].disabled = True
        self.fields['programming_comment'].required = False
        self.fields['programming_score'].required = False

    def clean(self):
        cleaned = super().clean()
        has_programming = cleaned.get('has_programming')
        programming_comment = (cleaned.get('programming_comment') or '').strip()
        programming_score = cleaned.get('programming_score')
        if has_programming:
            if not programming_comment:
                self.add_error('programming_comment', 'Informe o comentário de programação.')
            if programming_score is None:
                self.add_error('programming_score', 'Informe a nota de programação.')
        else:
            cleaned['programming_comment'] = ''
            cleaned['programming_score'] = None
        return cleaned


class CommercialOpportunityForm(forms.ModelForm):
    INTEREST_COURSE_PREFIX = 'course:'
    INTEREST_TYPE_PREFIX = 'type:'

    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativada'),
        (STATUS_INACTIVE, 'Desativada'),
    ]

    status = forms.ChoiceField(
        label='Status',
        choices=STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'input'}),
    )
    interest = forms.ChoiceField(
        label='Interesse',
        required=False,
        choices=[],
        widget=forms.Select(attrs={'class': 'input', 'data-interest-select': '1'}),
    )
    trial_lesson_kind = forms.ChoiceField(
        label='Tipo da aula',
        required=False,
        choices=[('', 'Selecione'), *Lesson.TRIAL_KIND_CHOICES],
        widget=forms.Select(attrs={'class': 'input'}),
    )
    trial_lesson_course = forms.ModelChoiceField(
        label='Curso da aula',
        required=False,
        queryset=Course.objects.none(),
        empty_label='Definir durante a aula',
        widget=forms.Select(attrs={'class': 'input'}),
    )
    trial_lesson_student_name = forms.CharField(
        label='Nome da Criança/Adolescente',
        required=False,
        max_length=160,
        widget=forms.TextInput(attrs={
            'class': 'input',
            'placeholder': 'Opcional',
            'autocomplete': 'off',
        }),
    )
    trial_lesson_slot = forms.ChoiceField(
        label='Horário livre',
        required=False,
        choices=[],
        error_messages={'invalid_choice': 'Selecione um horário livre válido.'},
        widget=forms.RadioSelect(),
    )
    trial_lesson_notes = forms.CharField(
        label='Observação da aula',
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 2}),
    )
    class Meta:
        model = CommercialOpportunity
        fields = [
            'title', 'commercial_funnel', 'stage', 'origin',
            'interest', 'value', 'contact_name', 'contact_phone', 'next_follow_up_date', 'notes',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input readonly-code', 'readonly': 'readonly', 'aria-readonly': 'true'}),
            'commercial_funnel': forms.Select(attrs={'class': 'input'}),
            'stage': forms.Select(attrs={'class': 'input'}),
            'origin': forms.Select(attrs={'class': 'input'}),
            'value': forms.NumberInput(attrs={'class': 'input', 'min': '0', 'step': '0.01', 'data-opportunity-value': '1'}),
            'contact_name': forms.TextInput(attrs={'class': 'input'}),
            'contact_phone': forms.TextInput(attrs={'class': 'input'}),
            'next_follow_up_date': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'input', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 4}),
        }
        labels = {
            'title': 'Código da oportunidade',
            'commercial_funnel': 'Funil',
            'stage': 'Etapa',
            'origin': 'Origem',
            'value': 'Valor',
            'contact_name': 'Nome do responsável',
            'contact_phone': 'Telefone do responsável',
            'next_follow_up_date': 'Data próx. Follow-Up',
            'notes': 'Observações',
        }

    def __init__(self, *args, **kwargs):
        self.available_trial_slots = kwargs.pop('available_trial_slots', [])
        self.has_existing_trial_lesson = kwargs.pop('has_existing_trial_lesson', False)
        self.generated_title = kwargs.pop('generated_title', '')
        super().__init__(*args, **kwargs)
        self.dynamic_field_names = []
        self.selected_funnel = None
        self.interest_value_map = {}
        self.trial_lesson_payload = None
        if not self.is_bound and not (self.instance and self.instance.pk) and self.generated_title:
            self.fields['title'].initial = self.generated_title
        if not self.is_bound and not (self.instance and self.instance.pk) and not self.initial.get('next_follow_up_date'):
            self.initial['next_follow_up_date'] = timezone.localdate() + timedelta(days=1)
        self.fields['next_follow_up_date'].required = False
        self.fields['status'].initial = self.STATUS_ACTIVE if self.instance.active else self.STATUS_INACTIVE
        self._configure_interest_choices()
        self._configure_trial_lesson_fields()

        funnels = (
            CommercialFunnel.objects.filter(active=True)
            .select_related('funnel_model')
            .order_by('name')
        )
        if self.instance and self.instance.pk and self.instance.commercial_funnel_id:
            funnels = (
                CommercialFunnel.objects.filter(
                    pk__in=list(funnels.values_list('pk', flat=True)) + [self.instance.commercial_funnel_id]
                )
                .select_related('funnel_model')
                .order_by('name')
            )
        self.fields['commercial_funnel'].queryset = funnels
        self._configure_standard_field_querysets()

        selected_funnel_id = self._selected_funnel_id()
        if selected_funnel_id:
            self.selected_funnel = (
                CommercialFunnel.objects.select_related('funnel_model')
                .prefetch_related('funnel_model__fields')
                .filter(pk=selected_funnel_id)
                .first()
            )
        if self.selected_funnel:
            self._add_model_fields()

    @property
    def interest_value_map_json(self):
        return json.dumps(self.interest_value_map, ensure_ascii=False)

    @property
    def selected_stage_requires_trial_lesson(self):
        stage = self._selected_stage()
        return bool(stage and stage.requires_trial_lesson)

    def _configure_interest_choices(self):
        courses = Course.objects.all().order_by('name')
        course_choices = []
        for course in courses:
            choice_value = f'{self.INTEREST_COURSE_PREFIX}{course.pk}'
            course_choices.append((choice_value, course.name))
            self.interest_value_map[choice_value] = f'{course.value:.2f}'

        choices = [('', 'Selecione')]
        if course_choices:
            choices.append(('Cursos', course_choices))
        choices.append((
            'Outras opções',
            [
                (f'{self.INTEREST_TYPE_PREFIX}{value}', label)
                for value, label in CommercialOpportunity.INTEREST_TYPE_CHOICES
            ],
        ))
        self.fields['interest'].choices = choices
        if not self.is_bound:
            self.fields['interest'].initial = self._interest_initial()

    def _configure_trial_lesson_fields(self):
        courses = Course.objects.filter(active=True).order_by('name')
        if self.instance and self.instance.pk and self.instance.interest_course_id:
            courses = Course.objects.filter(
                pk__in=list(courses.values_list('pk', flat=True)) + [self.instance.interest_course_id]
            ).order_by('name')
        self.fields['trial_lesson_course'].queryset = courses
        if not self.is_bound and self.instance and self.instance.interest_course_id:
            self.fields['trial_lesson_course'].initial = self.instance.interest_course_id

        choices = [('', 'Não agendar agora')]
        choices.extend((slot['value'], slot['label']) for slot in self.available_trial_slots)
        self.fields['trial_lesson_slot'].choices = choices

    def _selected_stage(self):
        if self.is_bound:
            value = self.data.get(self.add_prefix('stage'))
        elif self.instance and self.instance.pk:
            value = self.instance.stage_id
        else:
            value = self.initial.get('stage')
            if isinstance(value, FunnelStage):
                value = value.pk
        try:
            return FunnelStage.objects.filter(pk=int(value)).first() if value else None
        except (TypeError, ValueError):
            return None

    def _interest_initial(self):
        if self.instance and self.instance.pk:
            if self.instance.interest_course_id:
                return f'{self.INTEREST_COURSE_PREFIX}{self.instance.interest_course_id}'
            if self.instance.interest_type:
                return f'{self.INTEREST_TYPE_PREFIX}{self.instance.interest_type}'
        return ''

    def _configure_standard_field_querysets(self):
        stages = FunnelStage.objects.filter(active=True).order_by('order', 'name')
        origins = OpportunityOrigin.objects.filter(active=True).order_by('name')

        if self.instance and self.instance.pk:
            if self.instance.stage_id:
                stages = FunnelStage.objects.filter(
                    pk__in=list(stages.values_list('pk', flat=True)) + [self.instance.stage_id]
                ).order_by('order', 'name')
            if self.instance.origin_id:
                origins = OpportunityOrigin.objects.filter(
                    pk__in=list(origins.values_list('pk', flat=True)) + [self.instance.origin_id]
                ).order_by('name')

        self.fields['stage'].queryset = stages
        self.fields['origin'].queryset = origins

    @property
    def custom_bound_fields(self):
        return [self[name] for name in self.dynamic_field_names]

    def _selected_funnel_id(self):
        if self.is_bound:
            value = self.data.get(self.add_prefix('commercial_funnel'))
        elif self.instance and self.instance.pk:
            value = self.instance.commercial_funnel_id
        else:
            value = self.initial.get('commercial_funnel')
            if isinstance(value, CommercialFunnel):
                value = value.pk
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    def _custom_initial(self, field):
        values = self.instance.field_values or {}
        value = values.get(str(field.pk), '')
        if field.field_type == FunnelModelField.TYPE_DATETIME and isinstance(value, str):
            return value[:16]
        if field.field_type == FunnelModelField.TYPE_BOOLEAN:
            if value is True:
                return 'true'
            if value is False:
                return 'false'
        return value

    def _add_model_fields(self):
        for model_field in self.selected_funnel.funnel_model.fields.all().order_by('order', 'id'):
            field_name = f'custom_{model_field.pk}'
            self.dynamic_field_names.append(field_name)
            label = model_field.name
            required = model_field.required
            initial = self._custom_initial(model_field)
            if model_field.field_type == FunnelModelField.TYPE_TEXT:
                self.fields[field_name] = forms.CharField(
                    label=label,
                    required=required,
                    initial=initial,
                    widget=forms.Textarea(attrs={'class': 'input', 'rows': 2}),
                )
            elif model_field.field_type == FunnelModelField.TYPE_DATETIME:
                self.fields[field_name] = forms.DateTimeField(
                    label=label,
                    required=required,
                    initial=initial,
                    input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
                    widget=forms.DateTimeInput(attrs={'class': 'input', 'type': 'datetime-local'}),
                )
            elif model_field.field_type == FunnelModelField.TYPE_BOOLEAN:
                choices = [('', 'Selecione'), ('true', 'Sim'), ('false', 'Não')]
                self.fields[field_name] = forms.ChoiceField(
                    label=label,
                    choices=choices,
                    required=required,
                    initial=initial,
                    widget=forms.Select(attrs={'class': 'input'}),
                )
            elif model_field.field_type == FunnelModelField.TYPE_SELECT:
                choices = [(option, option) for option in model_field.options]
                if not required:
                    choices = [('', 'Selecione')] + choices
                self.fields[field_name] = forms.ChoiceField(
                    label=label,
                    choices=choices,
                    required=required,
                    initial=initial,
                    widget=forms.Select(attrs={'class': 'input'}),
                )
            elif model_field.field_type == FunnelModelField.TYPE_INTEGER:
                self.fields[field_name] = forms.IntegerField(
                    label=label,
                    required=required,
                    initial=initial,
                    widget=forms.NumberInput(attrs={'class': 'input'}),
                )

    def clean_title(self):
        value = (self.cleaned_data.get('title') or '').strip()
        if self.instance and self.instance.pk:
            return self.instance.title
        if not value:
            value = self.generated_title or self.initial.get('title') or 'Oportunidade automática'
        return value

    def clean_contact_name(self):
        value = (self.cleaned_data.get('contact_name') or '').strip()
        if not value:
            raise forms.ValidationError('Informe o nome do responsável.')
        return value

    def clean_contact_phone(self):
        value = (self.cleaned_data.get('contact_phone') or '').strip()
        if not value:
            raise forms.ValidationError('Informe o telefone do responsável.')
        return value

    def clean(self):
        cleaned = super().clean()
        interest = cleaned.get('interest') or ''
        value = cleaned.get('value')
        stage = cleaned.get('stage')
        next_follow_up_date = cleaned.get('next_follow_up_date')
        cleaned['_interest_course'] = None
        cleaned['_interest_type'] = ''

        if is_lost_stage(stage):
            cleaned['status'] = self.STATUS_INACTIVE
            if not next_follow_up_date:
                cleaned['next_follow_up_date'] = add_months(timezone.localdate(), 3)
        elif not next_follow_up_date:
            self.add_error('next_follow_up_date', 'Informe a data do próximo follow-up.')

        if not interest:
            cleaned['value'] = None
        elif value is not None and value < 0:
            self.add_error('value', 'O valor não pode ser negativo.')

        if interest.startswith(self.INTEREST_COURSE_PREFIX):
            course_id = interest.removeprefix(self.INTEREST_COURSE_PREFIX)
            try:
                course = Course.objects.get(pk=course_id)
            except (Course.DoesNotExist, ValueError):
                self.add_error('interest', 'Selecione um curso válido.')
                return cleaned
            cleaned['_interest_course'] = course
            if value is None:
                cleaned['value'] = course.value
        elif interest.startswith(self.INTEREST_TYPE_PREFIX):
            interest_type = interest.removeprefix(self.INTEREST_TYPE_PREFIX)
            valid_types = {value for value, _ in CommercialOpportunity.INTEREST_TYPE_CHOICES}
            if interest_type not in valid_types:
                self.add_error('interest', 'Selecione uma opção de interesse válida.')
            else:
                cleaned['_interest_type'] = interest_type
        elif interest:
            self.add_error('interest', 'Selecione uma opção de interesse válida.')

        self._clean_trial_lesson(cleaned)
        return cleaned

    def _clean_trial_lesson(self, cleaned):
        stage = cleaned.get('stage')
        requires_trial_lesson = bool(stage and stage.requires_trial_lesson)
        slot_value = cleaned.get('trial_lesson_slot') or ''
        lesson_kind = cleaned.get('trial_lesson_kind') or ''
        course = cleaned.get('trial_lesson_course')
        student_name = (cleaned.get('trial_lesson_student_name') or '').strip()
        notes = (cleaned.get('trial_lesson_notes') or '').strip()

        if requires_trial_lesson and not self.has_existing_trial_lesson and not slot_value:
            self.add_error('trial_lesson_slot', 'Esta etapa exige agendar uma Aula Experimental ou Play.')

        if slot_value or lesson_kind or course or student_name:
            if not lesson_kind:
                self.add_error('trial_lesson_kind', 'Informe se a aula é Experimental ou Play.')
            if not slot_value:
                self.add_error('trial_lesson_slot', 'Selecione um horário livre para a aula.')

        if not slot_value:
            return

        slot_map = {slot['value']: slot for slot in self.available_trial_slots}
        slot = slot_map.get(slot_value)
        if not slot:
            self.add_error('trial_lesson_slot', 'Selecione um horário livre válido.')
            return

        if lesson_kind:
            self.trial_lesson_payload = {
                'trial_kind': lesson_kind,
                'course': course,
                'room': slot['room'],
                'date': slot['date'],
                'start_time': slot['start_time'],
                'end_time': slot['end_time'],
                'student_name': student_name,
                'notes': notes,
            }

    def _inferred_funnel_type(self):
        if self.selected_funnel and self.selected_funnel.funnel_model.funnel_type_id:
            return self.selected_funnel.funnel_model.funnel_type
        funnel = self.selected_funnel
        if not funnel and self.instance and self.instance.commercial_funnel_id:
            funnel = self.instance.commercial_funnel
        if not funnel:
            return self.instance.funnel_type if self.instance and self.instance.pk else None
        code = slugify(funnel.name)
        return FunnelType.objects.filter(code=code).first() or FunnelType.objects.filter(name__iexact=funnel.name).first()

    def save(self, commit=True):
        opportunity = super().save(commit=False)
        opportunity.active = self.cleaned_data.get('status') == self.STATUS_ACTIVE
        opportunity.funnel_type = self._inferred_funnel_type()
        opportunity.interest_course = self.cleaned_data.get('_interest_course')
        opportunity.interest_type = self.cleaned_data.get('_interest_type') or ''
        if not self.cleaned_data.get('interest'):
            opportunity.value = None
        elif opportunity.interest_course_id and opportunity.value is None:
            opportunity.value = opportunity.interest_course.value
        values = {}
        if self.selected_funnel:
            for model_field in self.selected_funnel.funnel_model.fields.all().order_by('order', 'id'):
                field_name = f'custom_{model_field.pk}'
                value = self.cleaned_data.get(field_name)
                if value in (None, ''):
                    continue
                if model_field.field_type == FunnelModelField.TYPE_BOOLEAN:
                    value = value == 'true'
                elif hasattr(value, 'isoformat'):
                    value = value.isoformat()
                values[str(model_field.pk)] = value
        opportunity.field_values = values
        if commit:
            opportunity.save()
        return opportunity


class EmployeeAbsenceForm(forms.ModelForm):
    class Meta:
        model = EmployeeAbsence
        fields = ['profile', 'absence_type', 'start_date', 'end_date', 'reason', 'active']
        widgets = {
            'profile': forms.Select(attrs={'class': 'input'}),
            'absence_type': forms.Select(attrs={'class': 'input'}),
            'start_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'reason': forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 200}),
            'active': forms.CheckboxInput(),
        }
        labels = {
            'profile': 'Colaborador',
            'absence_type': 'Tipo de ausência',
            'start_date': 'Data inicial',
            'end_date': 'Data final',
            'reason': 'Motivo',
            'active': 'Ativa',
        }
        help_texts = {
            'reason': 'Descreva o motivo em até 200 caracteres.',
            'active': 'Desmarque para cancelar a ausência sem apagar o histórico.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profiles = UserProfile.objects.select_related('user', 'position').filter(
            system_role=UserProfile.ROLE_OPERATOR,
            position__isnull=False,
        ).order_by('display_name')
        if self.instance and self.instance.pk:
            profiles = UserProfile.objects.filter(pk=self.instance.profile_id) | profiles
        self.fields['profile'].queryset = profiles.distinct()

    def clean_reason(self):
        reason = (self.cleaned_data.get('reason') or '').strip()
        if not reason:
            raise forms.ValidationError('Informe o motivo da ausência.')
        if len(reason) > 200:
            raise forms.ValidationError('O motivo deve ter no máximo 200 caracteres.')
        return reason

    def clean(self):
        cleaned = super().clean()
        profile = cleaned.get('profile')
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        active = cleaned.get('active')
        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError('A data final não pode ser anterior à data inicial.')
        if profile and start_date and end_date and active:
            overlaps = EmployeeAbsence.objects.filter(
                profile=profile,
                active=True,
                start_date__lte=end_date,
                end_date__gte=start_date,
            )
            if self.instance and self.instance.pk:
                overlaps = overlaps.exclude(pk=self.instance.pk)
            if overlaps.exists():
                raise forms.ValidationError('Já existe uma ausência ativa para este colaborador no período informado.')
        return cleaned


class TaskTemplateForm(forms.ModelForm):
    title = forms.CharField(
        label='Descrição',
        max_length=300,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 300}),
    )
    expected_result = forms.CharField(
        label='Resultado esperado',
        max_length=300,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 300}),
    )
    evidence_required = forms.CharField(
        label='Evidência exigida',
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 300}),
    )
    proof_location = forms.CharField(
        label='Onde comprovar',
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 300}),
    )
    notes = forms.CharField(
        label='Observações',
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 5, 'maxlength': 2000}),
    )

    class Meta:
        model = TaskTemplate
        fields = [
            'position', 'day_of_week', 'start_time', 'end_time', 'title',
            'expected_result', 'frequency', 'requires_evidence', 'evidence_required', 'proof_location',
            'notes', 'active',
        ]
        widgets = {
            'position': forms.Select(attrs={'class': 'input'}),
            'day_of_week': forms.Select(attrs={'class': 'input'}),
            'start_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
            'frequency': forms.Select(attrs={'class': 'input'}),
            'requires_evidence': forms.CheckboxInput(),
            'active': forms.CheckboxInput(),
        }
        labels = {
            'position': 'Aplica-se ao',
            'day_of_week': 'Dia da semana',
            'start_time': 'Início',
            'end_time': 'Fim',
            'frequency': 'Recorrência',
            'requires_evidence': 'Exigir evidência do usuário comum',
            'active': 'Ativa',
        }
        help_texts = {
            'requires_evidence': 'Desmarque quando o usuário comum só precisar atualizar status/observação, sem evidência.',
            'active': 'Desmarque para inativar sem apagar histórico.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        positions = Position.objects.filter(active=True).order_by('name')
        if self.instance and self.instance.pk:
            positions = Position.objects.filter(
                pk__in=list(positions.values_list('pk', flat=True)) + [self.instance.position_id]
            ).order_by('name')
        self.fields['position'].queryset = positions
        self.fields['requires_evidence'].initial = True
        self.fields['active'].initial = True

    def clean(self):
        cleaned = super().clean()
        start_time = cleaned.get('start_time')
        end_time = cleaned.get('end_time')
        if start_time and end_time and end_time <= start_time:
            raise forms.ValidationError('O horário de fim deve ser posterior ao horário de início.')
        return cleaned


class ActivitySuggestionCreateForm(forms.ModelForm):
    title = forms.CharField(
        label='Descrição',
        max_length=300,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 300}),
    )
    expected_result = forms.CharField(
        label='Resultado esperado',
        max_length=300,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 300}),
    )
    evidence_required = forms.CharField(
        label='Evidência exigida',
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 300}),
    )
    proof_location = forms.CharField(
        label='Onde comprovar',
        max_length=300,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 300}),
    )
    notes = forms.CharField(
        label='Observações',
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 5, 'maxlength': 2000}),
    )
    justification = forms.CharField(
        label='Justificativa da sugestão',
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 500}),
    )

    class Meta:
        model = ActivitySuggestion
        fields = [
            'day_of_week', 'start_time', 'end_time', 'title', 'expected_result',
            'frequency', 'requires_evidence', 'evidence_required', 'proof_location',
            'notes', 'justification',
        ]
        widgets = {
            'day_of_week': forms.Select(attrs={'class': 'input'}),
            'start_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
            'frequency': forms.Select(attrs={'class': 'input'}),
            'requires_evidence': forms.CheckboxInput(),
        }
        labels = {
            'day_of_week': 'Dia da semana',
            'start_time': 'Início',
            'end_time': 'Fim',
            'frequency': 'Recorrência',
            'requires_evidence': 'Exigir evidência do usuário comum',
        }
        help_texts = {
            'requires_evidence': 'Desmarque se a atividade sugerida não precisa de evidência anexada/textual.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_time'].required = True
        self.fields['end_time'].required = True
        self.fields['requires_evidence'].initial = True

    def clean(self):
        cleaned = super().clean()
        start_time = cleaned.get('start_time')
        end_time = cleaned.get('end_time')
        if start_time and end_time and end_time <= start_time:
            raise forms.ValidationError('O horário de fim deve ser posterior ao horário de início.')
        return cleaned


class ActivitySuggestionReviewForm(ActivitySuggestionCreateForm):
    review_note = forms.CharField(
        label='Observação da revisão',
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 500}),
    )

    class Meta(ActivitySuggestionCreateForm.Meta):
        fields = ActivitySuggestionCreateForm.Meta.fields + ['review_note']


class ActivityDeactivationSuggestionForm(forms.Form):
    activities = forms.ModelMultipleChoiceField(
        label='Atividades ativas',
        queryset=TaskTemplate.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={'required': 'Selecione pelo menos uma atividade para sugerir desativação.'},
    )
    justification = forms.CharField(
        label='Justificativa',
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 3, 'maxlength': 500}),
    )

    def __init__(self, *args, position=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.position = position
        if position:
            self.fields['activities'].queryset = TaskTemplate.objects.filter(
                position=position,
                active=True,
            ).order_by('day_of_week', 'start_time', 'order', 'title')
            self.fields['activities'].label_from_instance = self._activity_label

    def _activity_label(self, template):
        start = template.start_time.strftime('%H:%M') if template.start_time else '--:--'
        end = template.end_time.strftime('%H:%M') if template.end_time else 'sem fim'
        return f'{template.get_day_of_week_display()} · {start}-{end} · {template.title}'


class UserCreateForm(forms.Form):
    """Cadastro de usuário feito por administrador.

    A senha é gerada automaticamente e exibida uma única vez ao administrador.
    """

    full_name = forms.CharField(label='Nome completo', max_length=120, widget=forms.TextInput(attrs={'class': 'input'}))
    username = forms.CharField(label='Usuário de login', max_length=150, widget=forms.TextInput(attrs={'class': 'input'}))
    email = forms.EmailField(label='E-mail', required=False, widget=forms.EmailInput(attrs={'class': 'input'}))
    role = forms.ChoiceField(label='Função/perfil no sistema', choices=[], widget=forms.Select(attrs={'class': 'input'}))
    active = forms.BooleanField(label='Ativo', required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('ADMIN', 'Administrador')]
        choices += [(f'POSITION:{p.id}', p.name) for p in Position.objects.filter(active=True).order_by('name')]
        self.fields['role'].choices = choices
        self.generated_password = None

    def clean_username(self):
        username = self.cleaned_data['username'].strip().lower()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Já existe usuário com este login.')
        return username

    def save(self):
        full_name = self.cleaned_data['full_name'].strip()
        role = self.cleaned_data['role']
        is_admin = role == 'ADMIN'
        position = None
        if role.startswith('POSITION:'):
            position_id = role.split(':', 1)[1]
            position = Position.objects.get(pk=position_id, active=True)

        self.generated_password = generate_temporary_password()
        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data.get('email') or '',
            password=self.generated_password,
            first_name=full_name,
            is_active=self.cleaned_data.get('active', True),
        )
        user.is_staff = is_admin
        user.is_superuser = is_admin
        user.save()

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.display_name = full_name
        profile.system_role = UserProfile.ROLE_ADMIN if is_admin else UserProfile.ROLE_OPERATOR
        profile.position = None if is_admin else position
        profile.active = self.cleaned_data.get('active', True)
        profile.must_change_password = should_force_password_change_on_first_login()
        profile.save()
        return user


class UserUpdateForm(forms.Form):
    full_name = forms.CharField(label='Nome completo', max_length=120, widget=forms.TextInput(attrs={'class': 'input'}))
    username = forms.CharField(label='Usuário de login', max_length=150, widget=forms.TextInput(attrs={'class': 'input'}))
    email = forms.EmailField(label='E-mail', required=False, widget=forms.EmailInput(attrs={'class': 'input'}))
    role = forms.ChoiceField(label='Função/perfil no sistema', choices=[], widget=forms.Select(attrs={'class': 'input'}))
    active = forms.BooleanField(label='Ativo', required=False)

    def __init__(self, *args, user_obj=None, **kwargs):
        self.user_obj = user_obj
        super().__init__(*args, **kwargs)
        choices = [('ADMIN', 'Administrador')]
        positions = Position.objects.filter(active=True).order_by('name')
        if user_obj and hasattr(user_obj, 'userprofile') and user_obj.userprofile.position_id:
            positions = Position.objects.filter(
                pk__in=list(positions.values_list('pk', flat=True)) + [user_obj.userprofile.position_id]
            ).order_by('name')
        choices += [(f'POSITION:{p.id}', f'{p.name}{" (inativo)" if not p.active else ""}') for p in positions]
        self.fields['role'].choices = choices

    def clean_username(self):
        username = self.cleaned_data['username'].strip().lower()
        qs = User.objects.filter(username=username)
        if self.user_obj:
            qs = qs.exclude(pk=self.user_obj.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe usuário com este login.')
        return username

    def save(self):
        user = self.user_obj
        profile = user.userprofile
        full_name = self.cleaned_data['full_name'].strip()
        role = self.cleaned_data['role']
        is_admin = role == 'ADMIN'
        position = None
        if role.startswith('POSITION:'):
            position_id = role.split(':', 1)[1]
            position = Position.objects.get(pk=position_id)

        user.username = self.cleaned_data['username']
        user.email = self.cleaned_data.get('email') or ''
        user.first_name = full_name
        user.is_active = self.cleaned_data.get('active', False)
        user.is_staff = is_admin
        user.is_superuser = is_admin
        user.save()

        profile.display_name = full_name
        profile.system_role = UserProfile.ROLE_ADMIN if is_admin else UserProfile.ROLE_OPERATOR
        profile.position = None if is_admin else position
        profile.active = self.cleaned_data.get('active', False)
        profile.save()
        return user


class AdminPasswordResetForm(forms.Form):
    """Redefinição administrativa de senha.

    A nova senha é gerada automaticamente e exibida uma única vez ao administrador.
    """

    confirm = forms.BooleanField(
        label='Confirmo que desejo gerar uma nova senha temporária para este usuário',
        required=True,
    )

    def __init__(self, *args, user_obj=None, **kwargs):
        self.user_obj = user_obj
        self.generated_password = None
        super().__init__(*args, **kwargs)

    def save(self):
        self.generated_password = generate_temporary_password()
        self.user_obj.set_password(self.generated_password)
        self.user_obj.save(update_fields=['password'])
        profile, _ = UserProfile.objects.get_or_create(user=self.user_obj)
        profile.must_change_password = should_force_password_change_on_first_login()
        profile.save(update_fields=['must_change_password'])
        return self.user_obj


class BackupConfigurationForm(forms.ModelForm):
    remote_name = forms.CharField(
        label='Conta/remoto rclone',
        required=False,
        max_length=80,
        widget=forms.TextInput(attrs={'class': 'input', 'list': 'rclone-remotes', 'placeholder': 'gdrive'}),
        help_text='Este remoto define qual conta Google Drive ou OneDrive sera usada.',
    )
    remote_folder = forms.CharField(
        label='Pasta no Drive/OneDrive',
        required=False,
        max_length=220,
        widget=forms.TextInput(attrs={'class': 'input', 'placeholder': 'MyRobotBackups/checklist'}),
        help_text='Pasta onde os backups serao gravados dentro da conta escolhida.',
    )

    class Meta:
        model = BackupConfiguration
        fields = ['cloud_provider', 'backup_time', 'retention_days', 'active']
        widgets = {
            'cloud_provider': forms.Select(attrs={'class': 'input'}),
            'backup_time': forms.TimeInput(attrs={'class': 'input', 'type': 'time'}),
            'retention_days': forms.NumberInput(attrs={'class': 'input', 'min': 1, 'max': 3650}),
            'active': forms.CheckboxInput(),
        }
        help_texts = {
            'cloud_provider': 'Escolha somente backup local, Google Drive ou OneDrive.',
            'backup_time': 'Horario local em que o backup automatico diario deve rodar.',
            'retention_days': 'Backups locais e na nuvem mais antigos que este prazo sao removidos apos um backup bem-sucedido.',
            'active': 'Quando marcado, o backup local tambem sera copiado para o caminho remoto configurado.',
        }

    def __init__(self, *args, rclone_remotes=None, **kwargs):
        super().__init__(*args, **kwargs)
        remote_name, remote_folder = split_remote_path(self.instance.remote_path if self.instance else '')
        self.fields['remote_name'].initial = remote_name
        self.fields['remote_folder'].initial = remote_folder
        self.rclone_remotes = set(rclone_remotes or [])

    def clean_retention_days(self):
        value = self.cleaned_data['retention_days']
        if value < 1:
            raise forms.ValidationError('Informe pelo menos 1 dia de retencao.')
        if value > 3650:
            raise forms.ValidationError('Use no maximo 3650 dias de retencao local/nuvem.')
        return value

    def clean(self):
        cleaned = super().clean()
        active = cleaned.get('active')
        provider = cleaned.get('cloud_provider')
        remote_name = (cleaned.get('remote_name') or '').strip().rstrip(':')
        remote_folder = (cleaned.get('remote_folder') or '').strip().strip('/')
        cleaned['remote_name'] = remote_name
        cleaned['remote_folder'] = remote_folder
        remote_path = build_remote_path(remote_name, remote_folder)

        if provider == BackupConfiguration.PROVIDER_NONE:
            if active:
                raise forms.ValidationError('Escolha Google Drive ou OneDrive para ativar envio em nuvem.')
            cleaned['remote_path'] = ''
            return cleaned

        if active and not remote_name:
            raise forms.ValidationError('Informe qual conta/remoto rclone deve ser usado.')
        if active and not remote_folder:
            raise forms.ValidationError('Informe a pasta de destino para o backup em nuvem.')
        if ':' in remote_name:
            raise forms.ValidationError('Informe apenas o nome do remoto, sem dois-pontos.')
        if self.rclone_remotes and remote_name and remote_name not in self.rclone_remotes:
            raise forms.ValidationError('O remoto informado não aparece no rclone deste container.')
        cleaned['remote_path'] = remote_path
        return cleaned

    def save(self, commit=True):
        config = super().save(commit=False)
        config.remote_path = self.cleaned_data.get('remote_path', '')
        if commit:
            config.save()
        return config


class AdminPasswordConfirmationForm(forms.Form):
    admin_password = forms.CharField(
        label='Senha do administrador',
        widget=forms.PasswordInput(attrs={
            'class': 'input',
            'autocomplete': 'current-password',
            'placeholder': 'Confirme sua senha',
        }),
        help_text='Obrigatoria para restaurar backups.',
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_admin_password(self):
        password = self.cleaned_data['admin_password']
        if not self.user or not self.user.check_password(password):
            raise forms.ValidationError('Senha incorreta.')
        return password


class BackupRestorePasswordForm(AdminPasswordConfirmationForm):
    pass


class BackupUploadForm(AdminPasswordConfirmationForm):
    backup_file = forms.FileField(
        label='Arquivo de backup',
        widget=forms.ClearableFileInput(attrs={'class': 'input', 'accept': '.zip,.tar,.gz,.tgz,.dump'}),
        help_text='Envie um pacote .tar.gz/.tgz/.zip contendo db.dump e, opcionalmente, media.tar.gz; ou envie somente db.dump.',
    )

    def clean_backup_file(self):
        uploaded = self.cleaned_data['backup_file']
        name = uploaded.name.lower()
        allowed = name.endswith(('.zip', '.tar', '.tar.gz', '.tgz', '.dump'))
        if not allowed:
            raise forms.ValidationError('Envie um arquivo .zip, .tar, .tar.gz, .tgz ou .dump.')
        max_bytes = 1024 * 1024 * 1024
        if uploaded.size > max_bytes:
            raise forms.ValidationError('Arquivo maior que 1 GB. Faça o upload manual para a pasta backups/.')
        return uploaded


# Aliases mantidos para compatibilidade com as views/URLs antigas.
EmployeeCreateForm = UserCreateForm
EmployeeUpdateForm = UserUpdateForm
