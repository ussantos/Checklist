from pathlib import Path
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from .models import ChecklistOccurrence, DailyNote, EmployeeAbsence, MetricRecord, MetricType, Position, TaskTemplate, UserProfile
from .security import generate_temporary_password, should_force_password_change_on_first_login


User = get_user_model()
ALLOWED_EVIDENCE_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.heic'}
ALLOWED_METRIC_EVIDENCE_EXTENSIONS = ALLOWED_EVIDENCE_EXTENSIONS | {
    '.txt', '.csv', '.tsv', '.xls', '.xlsx', '.ods', '.doc', '.docx',
    '.ppt', '.pptx', '.zip',
}


class MultipleFileInput(forms.ClearableFileInput):
    """Widget para upload de múltiplos arquivos.

    O Django não trata múltiplos arquivos em um FileField comum por padrão.
    Este widget permite usar request.FILES.getlist('evidence_files') na view.
    """

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Campo de múltiplos arquivos com validação simples de extensão e tamanho."""

    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        max_mb = min(int(getattr(settings, 'MAX_EVIDENCE_FILE_SIZE_MB', 5)), 5)
        max_bytes = max_mb * 1024 * 1024
        cleaned = []
        for uploaded in files:
            ext = Path(uploaded.name).suffix.lower()
            if ext not in ALLOWED_EVIDENCE_EXTENSIONS:
                raise forms.ValidationError(
                    f'Arquivo "{uploaded.name}" não permitido. Use PDF ou imagem: PDF, PNG, JPG, JPEG, WEBP, GIF ou HEIC.'
                )
            if uploaded.size > max_bytes:
                raise forms.ValidationError(f'Arquivo "{uploaded.name}" excede {max_mb} MB.')
            cleaned.append(uploaded)
        return cleaned


class MetricEvidenceFileField(forms.FileField):
    """Arquivo único para comprovação de indicador operacional."""

    def clean(self, data, initial=None):
        uploaded = super().clean(data, initial)
        if not uploaded:
            return uploaded
        ext = Path(uploaded.name).suffix.lower()
        if ext not in ALLOWED_METRIC_EVIDENCE_EXTENSIONS:
            raise forms.ValidationError(
                f'Arquivo "{uploaded.name}" não permitido. Use TXT, planilha, PDF, imagem, documento Office ou ZIP.'
            )
        max_mb = min(int(getattr(settings, 'MAX_EVIDENCE_FILE_SIZE_MB', 5)), 5)
        if uploaded.size > max_mb * 1024 * 1024:
            raise forms.ValidationError(f'Arquivo "{uploaded.name}" excede {max_mb} MB.')
        return uploaded


class OccurrenceUpdateForm(forms.ModelForm):
    """Formulário para registrar a execução de uma atividade."""

    evidence_files = MultipleFileField(
        required=False,
        label='Arquivos de evidência',
        help_text='Anexe PDF ou imagem de até 5 MB. Você pode selecionar mais de um arquivo.',
        widget=MultipleFileInput(attrs={'class': 'input', 'multiple': True, 'accept': '.pdf,image/*,.heic'}),
    )

    class Meta:
        model = ChecklistOccurrence
        fields = ['status', 'evidence_text', 'blocked_reason']
        widgets = {
            'status': forms.Select(attrs={'class': 'input'}),
            'evidence_text': forms.Textarea(attrs={'class': 'input', 'rows': 3, 'placeholder': 'Descreva a evidência objetiva da execução. Ex.: lead registrado, print anexado, e-mail enviado, aula registrada.'}),
            'blocked_reason': forms.Textarea(attrs={'class': 'input', 'rows': 2, 'placeholder': 'Obrigatório se a tarefa ficar pendente/bloqueada.'}),
        }

    def __init__(self, *args, **kwargs):
        self.has_existing_file = kwargs.pop('has_existing_file', False)
        self.requires_evidence = kwargs.pop('requires_evidence', True)
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = ChecklistOccurrence.OPERATIONAL_STATUS_CHOICES
        self.fields['blocked_reason'].label = 'Observação operacional'
        self.fields['blocked_reason'].widget.attrs['placeholder'] = 'Obrigatório quando a atividade estiver atrasada.'
        if not self.requires_evidence:
            self.fields.pop('evidence_text', None)
            self.fields.pop('evidence_files', None)

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get('status')
        evidence_text = (cleaned.get('evidence_text') or '').strip()
        blocked_reason = (cleaned.get('blocked_reason') or '').strip()
        new_files = cleaned.get('evidence_files') or []

        if self.requires_evidence and status == ChecklistOccurrence.STATUS_DONE and not evidence_text and not new_files and not self.has_existing_file:
            raise forms.ValidationError('Para concluir uma atividade, registre evidência textual ou anexe pelo menos um arquivo.')
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
    evidence_file = MetricEvidenceFileField(
        label='Evidência',
        required=False,
        help_text='Aceita TXT, planilha, PDF, imagem, documento Office ou ZIP de até 5 MB.',
        widget=forms.ClearableFileInput(attrs={
            'class': 'input',
            'accept': '.txt,.csv,.tsv,.xls,.xlsx,.ods,.pdf,image/*,.heic,.doc,.docx,.ppt,.pptx,.zip',
        }),
    )

    class Meta:
        model = MetricRecord
        fields = ['metric', 'date', 'value', 'notes', 'evidence_file']
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


# Aliases mantidos para compatibilidade com as views/URLs antigas.
EmployeeCreateForm = UserCreateForm
EmployeeUpdateForm = UserUpdateForm
