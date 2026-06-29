from datetime import time

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils import timezone


class Position(models.Model):
    """Cargo operacional que recebe um checklist.

    O sistema controla tarefas por cargo, mas cada funcionário possui login
    próprio. Assim, o histórico trabalhista/auditoria identifica a pessoa real
    que executou cada atividade sem exigir digitação manual do nome a cada tarefa.
    """

    code = models.SlugField('Código', max_length=80, unique=True)
    name = models.CharField('Cargo', max_length=140, unique=True)
    description = models.TextField('Descrição', blank=True)
    active = models.BooleanField('Ativo', default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Cargo'
        verbose_name_plural = 'Cargos'

    def __str__(self):
        return self.name


class FunnelType(models.Model):
    """Tipo comercial usado para classificar funis de atendimento."""

    code = models.SlugField('Código', max_length=80, unique=True)
    name = models.CharField('Tipo de funil', max_length=120, unique=True)
    active = models.BooleanField('Ativo', default=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Tipo de funil'
        verbose_name_plural = 'Tipos de funis'

    def __str__(self):
        return self.name

    def has_funnel_usage(self):
        for relation in self._meta.related_objects:
            accessor_name = relation.get_accessor_name()
            related_name = relation.related_model.__name__.lower()
            accessor_lower = accessor_name.lower()
            if (
                'funnel' not in accessor_lower
                and 'funil' not in accessor_lower
                and 'funnel' not in related_name
                and 'funil' not in related_name
            ):
                continue
            try:
                related = getattr(self, accessor_name, None)
            except ObjectDoesNotExist:
                continue
            if related is None:
                continue
            if hasattr(related, 'exists') and related.exists():
                return True
            if not hasattr(related, 'exists'):
                return True
        return False

    def can_be_deleted(self):
        return not self.has_funnel_usage()


class FunnelStage(models.Model):
    """Etapa operacional usada por modelos e instâncias de funis."""

    code = models.SlugField('Código', max_length=80, unique=True)
    name = models.CharField('Etapa', max_length=120, unique=True)
    description = models.TextField('Descrição', blank=True)
    order = models.PositiveIntegerField('Ordem', default=0)
    active = models.BooleanField('Ativa', default=True)
    created_at = models.DateTimeField('Criada em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizada em', auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Etapa de funil'
        verbose_name_plural = 'Etapas de funis'

    def __str__(self):
        return self.name

    def has_usage(self):
        return self.funnel_models.exists()

    def can_be_deleted(self):
        return not self.has_usage()


class OpportunityOrigin(models.Model):
    """Origem de oportunidade comercial usada por modelos e funis."""

    code = models.SlugField('Código', max_length=80, unique=True)
    name = models.CharField('Origem', max_length=120, unique=True)
    description = models.TextField('Descrição', blank=True)
    active = models.BooleanField('Ativa', default=True)
    created_at = models.DateTimeField('Criada em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizada em', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Origem de oportunidade'
        verbose_name_plural = 'Origens de oportunidades'

    def __str__(self):
        return self.name

    def has_usage(self):
        return self.funnel_models.exists()

    def can_be_deleted(self):
        return not self.has_usage()


class FunnelModel(models.Model):
    """Modelo que define os campos usados para criar funis comerciais."""

    funnel_type = models.ForeignKey(FunnelType, on_delete=models.PROTECT, related_name='funnel_models', verbose_name='Tipo')
    stage = models.ForeignKey(FunnelStage, on_delete=models.PROTECT, related_name='funnel_models', verbose_name='Etapa')
    origin = models.ForeignKey(OpportunityOrigin, on_delete=models.PROTECT, related_name='funnel_models', verbose_name='Origem')
    responsible_name = models.CharField('Nome do responsável', max_length=120)
    responsible_phone = models.CharField('Telefone do responsável', max_length=30)
    active = models.BooleanField('Ativado', default=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['funnel_type__name', 'stage__order', 'stage__name', 'responsible_name']
        verbose_name = 'Modelo de funil'
        verbose_name_plural = 'Modelos de funis'

    def __str__(self):
        return f'{self.funnel_type.name} - {self.stage.name} - {self.responsible_name}'

    @property
    def status_label(self):
        return 'Ativado' if self.active else 'Desativado'

    def has_instantiated_funnels(self):
        for relation in self._meta.related_objects:
            if relation.related_model.__name__ == 'FunnelModelField':
                continue
            accessor_name = relation.get_accessor_name()
            related_model = relation.related_model.__name__.lower()
            accessor_lower = accessor_name.lower()
            if not any(
                token in accessor_lower or token in related_model
                for token in ['funnel', 'funil', 'opportunity', 'oportunidade', 'lead']
            ):
                continue
            try:
                related = getattr(self, accessor_name, None)
            except ObjectDoesNotExist:
                continue
            if related is None:
                continue
            if hasattr(related, 'exists') and related.exists():
                return True
            if not hasattr(related, 'exists'):
                return True
        return False

    def can_be_deleted(self):
        return not self.has_instantiated_funnels()


class FunnelModelField(models.Model):
    """Campo adicional configurável de um modelo de funil."""

    TYPE_TEXT = 'TEXT'
    TYPE_DATETIME = 'DATETIME'
    TYPE_BOOLEAN = 'BOOLEAN'
    TYPE_SELECT = 'SELECT'
    TYPE_INTEGER = 'INTEGER'
    FIELD_TYPE_CHOICES = [
        (TYPE_TEXT, 'Texto'),
        (TYPE_DATETIME, 'Data e Hora'),
        (TYPE_BOOLEAN, 'Verdadeiro/Falso'),
        (TYPE_SELECT, 'Caixa de Seleção'),
        (TYPE_INTEGER, 'Número Inteiro'),
    ]

    funnel_model = models.ForeignKey(FunnelModel, on_delete=models.CASCADE, related_name='fields')
    name = models.CharField('Nome do campo', max_length=120)
    field_type = models.CharField('Tipo do campo', max_length=20, choices=FIELD_TYPE_CHOICES)
    required = models.BooleanField('Obrigatório', default=False)
    options = models.JSONField('Opções', default=list, blank=True)
    order = models.PositiveIntegerField('Ordem', default=0)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['funnel_model', 'name'], name='unique_field_name_per_funnel_model'),
        ]
        verbose_name = 'Campo de modelo de funil'
        verbose_name_plural = 'Campos de modelos de funis'

    def __str__(self):
        return f'{self.funnel_model_id} - {self.name}'


class CommercialFunnel(models.Model):
    """Funil comercial criado a partir de um modelo de funil."""

    name = models.CharField('Nome do funil', max_length=160, unique=True)
    funnel_model = models.ForeignKey(FunnelModel, on_delete=models.PROTECT, related_name='funnels', verbose_name='Modelo de funil')
    active = models.BooleanField('Ativo', default=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Funil comercial'
        verbose_name_plural = 'Funis comerciais'

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """Perfil local do usuário autenticado.

    Usuários administradores acompanham todos os cargos e cadastram usuários.
    Usuários operacionais enxergam apenas o cargo vinculado.
    O campo display_name representa o nome completo do usuário.
    """

    ROLE_ADMIN = 'ADMIN'
    ROLE_OPERATOR = 'OPERATOR'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Administrador'),
        (ROLE_OPERATOR, 'Operacional'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    display_name = models.CharField('Nome completo', max_length=120)
    system_role = models.CharField('Perfil', max_length=20, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    active = models.BooleanField('Ativo', default=True)
    must_change_password = models.BooleanField(
        'Deve trocar senha no próximo login',
        default=False,
        help_text='Quando marcado, o usuário é redirecionado obrigatoriamente para a troca de senha antes de usar o sistema.',
    )

    class Meta:
        verbose_name = 'Perfil de usuário'
        verbose_name_plural = 'Perfis de usuário'

    def __str__(self):
        if self.position:
            return f'{self.display_name} ({self.position.name})'
        return self.display_name

    @property
    def is_admin_role(self):
        return self.system_role == self.ROLE_ADMIN or self.user.is_staff or self.user.is_superuser


class EmployeeAbsence(models.Model):
    """Ausência planejada ou justificada de um colaborador operacional."""

    TYPE_VACATION = 'VACATION'
    TYPE_JUSTIFIED = 'JUSTIFIED'
    TYPE_CHOICES = [
        (TYPE_VACATION, 'Férias'),
        (TYPE_JUSTIFIED, 'Ausência justificada'),
    ]

    profile = models.ForeignKey(UserProfile, on_delete=models.PROTECT, related_name='absences')
    absence_type = models.CharField('Tipo', max_length=20, choices=TYPE_CHOICES)
    start_date = models.DateField('Início')
    end_date = models.DateField('Fim')
    reason = models.CharField('Motivo', max_length=200)
    active = models.BooleanField('Ativa', default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_absences')
    created_at = models.DateTimeField('Criada em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizada em', auto_now=True)

    class Meta:
        ordering = ['-start_date', 'profile__display_name']
        indexes = [
            models.Index(fields=['start_date', 'end_date', 'active']),
            models.Index(fields=['profile', 'start_date', 'end_date']),
        ]
        verbose_name = 'Ausência de colaborador'
        verbose_name_plural = 'Ausências de colaboradores'

    def __str__(self):
        return f'{self.profile.display_name} - {self.get_absence_type_display()} ({self.start_date:%d/%m/%Y} a {self.end_date:%d/%m/%Y})'

    def covers(self, target_date):
        return self.active and self.start_date <= target_date <= self.end_date


class TaskTemplate(models.Model):
    """Tarefa recorrente de checklist vinculada a um cargo."""

    FREQ_DAILY = 'DAILY'
    FREQ_WEEKLY = 'WEEKLY'
    FREQ_BIWEEKLY = 'BIWEEKLY'
    FREQ_MONTHLY = 'MONTHLY'
    FREQ_ANNUAL = 'ANNUAL'
    FREQ_CONDITIONAL = 'CONDITIONAL'
    FREQ_CHOICES = [
        (FREQ_DAILY, 'Diária'),
        (FREQ_WEEKLY, 'Semanal'),
        (FREQ_MONTHLY, 'Mensal'),
        (FREQ_ANNUAL, 'Anual'),
        (FREQ_BIWEEKLY, 'Quinzenal'),
        (FREQ_CONDITIONAL, 'Condicional'),
    ]

    WEEKDAY_CHOICES = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
    ]

    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='task_templates')
    title = models.CharField('Tarefa', max_length=300)
    description = models.TextField('Instruções', blank=True)
    frequency = models.CharField('Frequência', max_length=20, choices=FREQ_CHOICES, default=FREQ_DAILY)
    day_of_week = models.IntegerField('Dia da semana', choices=WEEKDAY_CHOICES, default=0)
    start_time = models.TimeField('Início previsto', blank=True, null=True)
    end_time = models.TimeField('Fim previsto', blank=True, null=True)
    category = models.CharField('Categoria', max_length=120, blank=True)
    expected_result = models.CharField('Resultado esperado', max_length=300, blank=True)
    requires_evidence = models.BooleanField(
        'Exige evidência',
        default=True,
        help_text='Quando marcado, o usuário comum deve registrar evidência ao concluir a atividade.',
    )
    evidence_required = models.CharField('Evidência exigida', max_length=300, blank=True)
    proof_location = models.CharField('Onde comprovar', max_length=300, blank=True)
    notes = models.TextField('Observações', blank=True)
    monthly_goal = models.CharField('Meta mensal relacionada', max_length=255, blank=True)
    source = models.CharField('Origem', max_length=120, default='Checklist REV06')
    order = models.PositiveIntegerField('Ordem', default=0)
    active = models.BooleanField('Ativa', default=True)

    class Meta:
        ordering = ['position__name', 'day_of_week', 'order', 'start_time', 'title']
        verbose_name = 'Modelo de tarefa'
        verbose_name_plural = 'Modelos de tarefa'

    def __str__(self):
        return f'{self.position.name} - {self.title}'

    def is_due_on(self, target_date):
        """Define se a tarefa deve aparecer no checklist da data."""
        if not self.active:
            return False
        if target_date.weekday() > 5:
            return False
        if target_date.weekday() != self.day_of_week:
            return False
        if self.frequency in [self.FREQ_DAILY, self.FREQ_WEEKLY, self.FREQ_CONDITIONAL]:
            return True
        if self.frequency == self.FREQ_BIWEEKLY:
            return target_date.isocalendar().week % 2 == 0
        if self.frequency == self.FREQ_MONTHLY:
            return 1 <= target_date.day <= 7
        if self.frequency == self.FREQ_ANNUAL:
            return target_date.month == 1 and 1 <= target_date.day <= 7
        return False


class ActivitySuggestion(models.Model):
    """Solicitação operacional de criação ou inativação de atividade."""

    TYPE_CREATE = 'CREATE'
    TYPE_DEACTIVATE = 'DEACTIVATE'
    TYPE_CHOICES = [
        (TYPE_CREATE, 'Adicionar atividade'),
        (TYPE_DEACTIVATE, 'Desativar atividade'),
    ]

    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendente'),
        (STATUS_APPROVED, 'Aprovada'),
        (STATUS_REJECTED, 'Rejeitada'),
    ]

    request_type = models.CharField('Tipo de solicitação', max_length=20, choices=TYPE_CHOICES)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='activity_suggestions')
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name='activity_suggestions')
    target_template = models.ForeignKey(
        TaskTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='deactivation_suggestions',
        verbose_name='Atividade indicada para inativação',
    )
    created_template = models.ForeignKey(
        TaskTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='creation_suggestions',
        verbose_name='Atividade criada',
    )
    title = models.CharField('Descrição', max_length=300, blank=True)
    expected_result = models.CharField('Resultado esperado', max_length=300, blank=True)
    frequency = models.CharField('Recorrência', max_length=20, choices=TaskTemplate.FREQ_CHOICES, default=TaskTemplate.FREQ_DAILY)
    day_of_week = models.IntegerField('Dia da semana', choices=TaskTemplate.WEEKDAY_CHOICES, default=0)
    start_time = models.TimeField('Início', blank=True, null=True)
    end_time = models.TimeField('Fim', blank=True, null=True)
    requires_evidence = models.BooleanField('Exige evidência', default=True)
    evidence_required = models.CharField('Evidência exigida', max_length=300, blank=True)
    proof_location = models.CharField('Onde comprovar', max_length=300, blank=True)
    notes = models.TextField('Observações', blank=True)
    justification = models.CharField('Justificativa', max_length=500, blank=True)
    review_note = models.CharField('Observação da revisão', max_length=500, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_activity_suggestions')
    reviewed_at = models.DateTimeField('Revisada em', blank=True, null=True)
    created_at = models.DateTimeField('Criada em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizada em', auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'request_type']),
            models.Index(fields=['position', 'status']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = 'Sugestão de atividade'
        verbose_name_plural = 'Sugestões de atividades'

    def __str__(self):
        subject = self.title or (self.target_template.title if self.target_template_id else 'Atividade')
        return f'{self.get_request_type_display()} - {subject}'

    @property
    def is_pending(self):
        return self.status == self.STATUS_PENDING


class ChecklistOccurrence(models.Model):
    """Execução real de uma tarefa em determinado dia."""

    STATUS_PLANNED = 'PLANNED'
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_DONE = 'DONE'
    STATUS_NOT_APPLICABLE = 'NOT_APPLICABLE'
    STATUS_BLOCKED = 'BLOCKED'
    STATUS_CHOICES = [
        (STATUS_PLANNED, 'Previsto'),
        (STATUS_IN_PROGRESS, 'Em andamento'),
        (STATUS_DONE, 'Concluído'),
        (STATUS_NOT_APPLICABLE, 'Não se aplica'),
        (STATUS_BLOCKED, 'Bloqueado/Pendente'),
    ]
    OPERATIONAL_STATUS_CHOICES = [
        (STATUS_PLANNED, 'Pendente'),
        (STATUS_IN_PROGRESS, 'Executando'),
        (STATUS_BLOCKED, 'Atrasada'),
        (STATUS_DONE, 'Concluída'),
    ]
    HISTORY_STATUS_CHOICES = OPERATIONAL_STATUS_CHOICES + [
        (STATUS_NOT_APPLICABLE, 'Não se aplica'),
    ]
    OPERATIONAL_STATUS_LABELS = dict(OPERATIONAL_STATUS_CHOICES)

    template = models.ForeignKey(TaskTemplate, on_delete=models.PROTECT, related_name='occurrences')
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name='occurrences')
    date = models.DateField('Data')
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    executor_full_name = models.CharField(
        'Nome completo do funcionário',
        max_length=180,
        blank=True,
        help_text='Preenchido automaticamente a partir do cadastro do usuário que atualizou a atividade.',
    )
    evidence_text = models.TextField('Evidência/observação', blank=True)
    evidence_file = models.FileField('Arquivo de evidência legado', upload_to='evidencias/%Y/%m/', blank=True, null=True)
    blocked_reason = models.TextField('Motivo de pendência/bloqueio', blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)
    completed_at = models.DateTimeField('Concluído em', blank=True, null=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='updated_occurrences')

    class Meta:
        unique_together = [('template', 'position', 'date')]
        ordering = ['date', 'position__name', 'template__order', 'template__start_time', 'template__title']
        indexes = [
            models.Index(fields=['date', 'position', 'status']),
            models.Index(fields=['position', 'status']),
        ]
        verbose_name = 'Execução de tarefa'
        verbose_name_plural = 'Execuções de tarefas'

    def __str__(self):
        return f'{self.date} - {self.position.name} - {self.template.title}'

    @property
    def operational_status_label(self):
        return self.OPERATIONAL_STATUS_LABELS.get(self.status, self.get_status_display())

    @property
    def operational_status_css(self):
        return self.status.lower()

    def mark_status(self, new_status, user=None):
        self.status = new_status
        self.updated_by = user
        if new_status == self.STATUS_DONE and not self.completed_at:
            self.completed_at = timezone.now()
        if new_status != self.STATUS_DONE:
            self.completed_at = None


class ChecklistOccurrenceStatusEvent(models.Model):
    """Evento auditável de transição de status de uma ocorrência."""

    occurrence = models.ForeignKey(ChecklistOccurrence, on_delete=models.CASCADE, related_name='status_events')
    previous_status = models.CharField('Status anterior', max_length=20, choices=ChecklistOccurrence.STATUS_CHOICES, blank=True)
    new_status = models.CharField('Novo status', max_length=20, choices=ChecklistOccurrence.STATUS_CHOICES)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='checklist_status_events')
    changed_at = models.DateTimeField('Alterado em', default=timezone.now)
    created_at = models.DateTimeField('Registrado em', auto_now_add=True)

    class Meta:
        ordering = ['changed_at', 'id']
        indexes = [
            models.Index(fields=['occurrence', 'changed_at']),
            models.Index(fields=['changed_at']),
            models.Index(fields=['new_status']),
        ]
        verbose_name = 'Evento de status de atividade'
        verbose_name_plural = 'Eventos de status de atividades'

    def __str__(self):
        return f'{self.occurrence_id} - {self.previous_status or "-"} -> {self.new_status}'

    @property
    def previous_status_label(self):
        if not self.previous_status:
            return '-'
        return ChecklistOccurrence.OPERATIONAL_STATUS_LABELS.get(self.previous_status, self.get_previous_status_display())

    @property
    def new_status_label(self):
        return ChecklistOccurrence.OPERATIONAL_STATUS_LABELS.get(self.new_status, self.get_new_status_display())


class EvidenceAttachment(models.Model):
    """Arquivo de evidência vinculado a uma execução de tarefa.

    Permite mais de um anexo por atividade: PDF, imagem, print ou foto.
    O texto da evidência continua no campo `evidence_text` da ocorrência.
    """

    occurrence = models.ForeignKey(ChecklistOccurrence, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField('Arquivo', upload_to='evidencias/%Y/%m/')
    original_name = models.CharField('Nome original', max_length=255, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField('Enviado em', auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Anexo de evidência'
        verbose_name_plural = 'Anexos de evidência'

    def __str__(self):
        return self.original_name or self.file.name


class DailyNote(models.Model):
    """Observação geral de um cargo em um dia."""

    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='daily_notes')
    date = models.DateField('Data')
    executor_full_name = models.CharField('Nome completo do responsável pelo resumo', max_length=180, blank=True)
    notes = models.TextField('Resumo do dia', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        unique_together = [('position', 'date')]
        ordering = ['-date', 'position__name']
        verbose_name = 'Resumo diário'
        verbose_name_plural = 'Resumos diários'

    def __str__(self):
        return f'{self.date} - {self.position.name}'


class MetricType(models.Model):
    """Indicador acompanhado no dashboard."""

    FREQ_DAILY = 'DAILY'
    FREQ_WEEKLY = 'WEEKLY'
    FREQ_MONTHLY = 'MONTHLY'
    FREQ_ANNUAL = 'ANNUAL'
    FREQ_CHOICES = [
        (FREQ_DAILY, 'Diário'),
        (FREQ_WEEKLY, 'Semanal'),
        (FREQ_MONTHLY, 'Mensal'),
        (FREQ_ANNUAL, 'Anual'),
    ]

    code = models.SlugField('Código', max_length=80, unique=True)
    name = models.CharField('Indicador', max_length=140)
    area = models.CharField('Área', max_length=70, default='Operacional')
    frequency = models.CharField('Frequência', max_length=20, choices=FREQ_CHOICES, default=FREQ_MONTHLY)
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='metric_types', null=True, blank=True)
    activity = models.ForeignKey(TaskTemplate, on_delete=models.PROTECT, related_name='metric_types', null=True, blank=True)
    monthly_target = models.DecimalField('Meta mensal', max_digits=10, decimal_places=2, default=0)
    unit = models.CharField('Unidade', max_length=40, default='un')
    active = models.BooleanField('Ativo', default=True)

    class Meta:
        ordering = ['position__name', 'name']
        verbose_name = 'Indicador'
        verbose_name_plural = 'Indicadores'

    def __str__(self):
        return self.name


class MetricRecord(models.Model):
    """Registro diário/semanal/mensal de indicador."""

    metric = models.ForeignKey(MetricType, on_delete=models.CASCADE, related_name='records')
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='metric_records')
    date = models.DateField('Data')
    executor_full_name = models.CharField('Nome completo do funcionário', max_length=180, blank=True)
    value = models.DecimalField('Valor', max_digits=10, decimal_places=2)
    notes = models.TextField('Observações', blank=True)
    evidence_file = models.FileField('Arquivo de evidência', upload_to='metricas/%Y/%m/', blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        ordering = ['-date', 'metric__name']
        verbose_name = 'Registro de indicador'
        verbose_name_plural = 'Registros de indicadores'

    def __str__(self):
        return f'{self.date} - {self.metric.name}: {self.value}'


class BackupConfiguration(models.Model):
    """Configuracao operacional de backup em nuvem via rclone."""

    PROVIDER_NONE = 'NONE'
    PROVIDER_GOOGLE_DRIVE = 'GOOGLE_DRIVE'
    PROVIDER_ONEDRIVE = 'ONEDRIVE'
    PROVIDER_CHOICES = [
        (PROVIDER_NONE, 'Somente backup local'),
        (PROVIDER_GOOGLE_DRIVE, 'Google Drive'),
        (PROVIDER_ONEDRIVE, 'OneDrive'),
    ]

    cloud_provider = models.CharField('Destino em nuvem', max_length=20, choices=PROVIDER_CHOICES, default=PROVIDER_NONE)
    remote_path = models.CharField(
        'Caminho remoto rclone',
        max_length=255,
        blank=True,
        help_text='Exemplo: gdrive:MyRobotBackups/checklist ou onedrive:MyRobotBackups/checklist.',
    )
    retention_days = models.PositiveIntegerField('Retencao local em dias', default=30)
    backup_time = models.TimeField('Horario diario do backup', default=time(20, 0))
    active = models.BooleanField('Enviar backup para nuvem', default=False)
    last_scheduled_run_at = models.DateTimeField('Ultimo backup agendado', blank=True, null=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'Configuracao de backup'
        verbose_name_plural = 'Configuracoes de backup'

    def __str__(self):
        return self.get_cloud_provider_display()

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ActivityLog(models.Model):
    """Trilha de auditoria simples."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField('Ação', max_length=120)
    object_type = models.CharField('Tipo de objeto', max_length=80, blank=True)
    object_id = models.CharField('ID do objeto', max_length=80, blank=True)
    object_label = models.CharField('Nome/descrição do item', max_length=300, blank=True)
    previous_values = models.JSONField('Valores anteriores', default=dict, blank=True)
    new_values = models.JSONField('Valores novos', default=dict, blank=True)
    details = models.TextField('Detalhes', blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['object_type', 'action']),
            models.Index(fields=['actor', 'created_at']),
        ]
        verbose_name = 'Log de atividade'
        verbose_name_plural = 'Logs de atividade'

    def __str__(self):
        return f'{self.created_at:%d/%m/%Y %H:%M} - {self.action}'
