from django.conf import settings
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


class TaskTemplate(models.Model):
    """Tarefa recorrente de checklist vinculada a um cargo."""

    FREQ_DAILY = 'DAILY'
    FREQ_WEEKLY = 'WEEKLY'
    FREQ_BIWEEKLY = 'BIWEEKLY'
    FREQ_MONTHLY = 'MONTHLY'
    FREQ_CONDITIONAL = 'CONDITIONAL'
    FREQ_CHOICES = [
        (FREQ_DAILY, 'Diária'),
        (FREQ_WEEKLY, 'Semanal'),
        (FREQ_BIWEEKLY, 'Quinzenal'),
        (FREQ_MONTHLY, 'Mensal'),
        (FREQ_CONDITIONAL, 'Condicional'),
    ]

    WEEKDAY_CHOICES = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
    ]

    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='task_templates')
    title = models.CharField('Tarefa', max_length=255)
    description = models.TextField('Instruções', blank=True)
    frequency = models.CharField('Frequência', max_length=20, choices=FREQ_CHOICES, default=FREQ_DAILY)
    day_of_week = models.IntegerField('Dia da semana', choices=WEEKDAY_CHOICES, default=0)
    start_time = models.TimeField('Início previsto', blank=True, null=True)
    end_time = models.TimeField('Fim previsto', blank=True, null=True)
    category = models.CharField('Categoria', max_length=120, blank=True)
    evidence_required = models.CharField('Evidência esperada', max_length=255, blank=True)
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
        if target_date.weekday() > 4:
            return False
        if target_date.weekday() != self.day_of_week:
            return False
        if self.frequency in [self.FREQ_DAILY, self.FREQ_WEEKLY, self.FREQ_CONDITIONAL]:
            return True
        if self.frequency == self.FREQ_BIWEEKLY:
            return target_date.isocalendar().week % 2 == 0
        if self.frequency == self.FREQ_MONTHLY:
            return 1 <= target_date.day <= 7
        return False


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

    def mark_status(self, new_status, user=None):
        self.status = new_status
        self.updated_by = user
        if new_status == self.STATUS_DONE and not self.completed_at:
            self.completed_at = timezone.now()
        if new_status != self.STATUS_DONE:
            self.completed_at = None


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

    code = models.SlugField('Código', max_length=80, unique=True)
    name = models.CharField('Indicador', max_length=140)
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='metric_types', null=True, blank=True)
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


class ActivityLog(models.Model):
    """Trilha de auditoria simples."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField('Ação', max_length=120)
    object_type = models.CharField('Tipo de objeto', max_length=80, blank=True)
    object_id = models.CharField('ID do objeto', max_length=80, blank=True)
    details = models.TextField('Detalhes', blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Log de atividade'
        verbose_name_plural = 'Logs de atividade'

    def __str__(self):
        return f'{self.created_at:%d/%m/%Y %H:%M} - {self.action}'
