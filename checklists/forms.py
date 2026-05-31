from pathlib import Path
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import ChecklistOccurrence, DailyNote, MetricRecord, Position, UserProfile


User = get_user_model()
ALLOWED_EVIDENCE_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.heic'}


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
        max_mb = int(getattr(settings, 'MAX_EVIDENCE_FILE_SIZE_MB', 15))
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


class OccurrenceUpdateForm(forms.ModelForm):
    """Formulário para registrar a execução de uma atividade.

    O nome completo do funcionário não é digitado: ele é preenchido
    automaticamente pela view a partir do cadastro do usuário autenticado.
    """

    evidence_files = MultipleFileField(
        required=False,
        label='Arquivos de evidência',
        help_text='Anexe PDF, imagens ou prints. Você pode selecionar mais de um arquivo.',
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
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get('status')
        evidence_text = (cleaned.get('evidence_text') or '').strip()
        blocked_reason = (cleaned.get('blocked_reason') or '').strip()
        new_files = cleaned.get('evidence_files') or []

        if status == ChecklistOccurrence.STATUS_DONE and not evidence_text and not new_files and not self.has_existing_file:
            raise forms.ValidationError('Para concluir uma atividade, registre evidência textual ou anexe pelo menos um arquivo.')
        if status == ChecklistOccurrence.STATUS_BLOCKED and not blocked_reason:
            raise forms.ValidationError('Informe o motivo quando a atividade ficar bloqueada ou pendente.')
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
        fields = ['metric', 'date', 'value', 'notes', 'evidence_file']
        widgets = {
            'metric': forms.Select(attrs={'class': 'input'}),
            'date': forms.DateInput(attrs={'class': 'input', 'type': 'date'}),
            'value': forms.NumberInput(attrs={'class': 'input', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'input', 'rows': 3}),
            'evidence_file': forms.ClearableFileInput(attrs={'class': 'input', 'accept': '.pdf,image/*,.heic'}),
        }


class UserCreateForm(forms.Form):
    """Cadastro de usuário feito por administrador.

    O primeiro usuário técnico é `checkupadmin`. Depois disso, administradores
    cadastram usuários nominais com um dos perfis:
    Administrador, Atendente Comercial ou Instrutor de Aula Livre.
    """

    full_name = forms.CharField(label='Nome completo', max_length=120, widget=forms.TextInput(attrs={'class': 'input'}))
    username = forms.CharField(label='Usuário de login', max_length=150, widget=forms.TextInput(attrs={'class': 'input'}))
    email = forms.EmailField(label='E-mail', required=False, widget=forms.EmailInput(attrs={'class': 'input'}))
    role = forms.ChoiceField(label='Função/perfil no sistema', choices=[], widget=forms.Select(attrs={'class': 'input'}))
    password1 = forms.CharField(label='Senha forte', widget=forms.PasswordInput(attrs={'class': 'input'}), help_text='Mínimo de 12 caracteres, maiúscula, minúscula, número e caractere especial.')
    password2 = forms.CharField(label='Confirmar senha', widget=forms.PasswordInput(attrs={'class': 'input'}))
    active = forms.BooleanField(label='Ativo', required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('ADMIN', 'Administrador')]
        choices += [(f'POSITION:{p.id}', p.name) for p in Position.objects.filter(active=True).order_by('name')]
        self.fields['role'].choices = choices

    def clean_username(self):
        username = self.cleaned_data['username'].strip().lower()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Já existe usuário com este login.')
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('As senhas não conferem.')
        if p1:
            validate_password(p1)
        return cleaned

    def save(self):
        full_name = self.cleaned_data['full_name'].strip()
        role = self.cleaned_data['role']
        is_admin = role == 'ADMIN'
        position = None
        if role.startswith('POSITION:'):
            position_id = role.split(':', 1)[1]
            position = Position.objects.get(pk=position_id, active=True)

        user = User.objects.create_user(
            username=self.cleaned_data['username'],
            email=self.cleaned_data.get('email') or '',
            password=self.cleaned_data['password1'],
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
        choices += [(f'POSITION:{p.id}', p.name) for p in Position.objects.filter(active=True).order_by('name')]
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
            position = Position.objects.get(pk=position_id, active=True)

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
    password1 = forms.CharField(label='Nova senha forte', widget=forms.PasswordInput(attrs={'class': 'input'}), help_text='Mínimo de 12 caracteres, maiúscula, minúscula, número e caractere especial.')
    password2 = forms.CharField(label='Confirmar senha', widget=forms.PasswordInput(attrs={'class': 'input'}))

    def __init__(self, *args, user_obj=None, **kwargs):
        self.user_obj = user_obj
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1')
        p2 = cleaned.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('As senhas não conferem.')
        if p1:
            validate_password(p1, user=self.user_obj)
        return cleaned

    def save(self):
        self.user_obj.set_password(self.cleaned_data['password1'])
        self.user_obj.save(update_fields=['password'])
        return self.user_obj


# Aliases mantidos para compatibilidade com as views/URLs antigas.
EmployeeCreateForm = UserCreateForm
EmployeeUpdateForm = UserUpdateForm
