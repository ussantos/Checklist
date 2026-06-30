from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from django.utils.text import slugify


LUNCH_START = time(12, 0)
LUNCH_END = time(13, 0)


def is_lunch_boundary_time(value):
    return value is not None and LUNCH_START < value < LUNCH_END


def lunch_boundary_errors(start_time, end_time):
    errors = {}
    if is_lunch_boundary_time(start_time):
        errors['start_time'] = 'A aula/horário não pode iniciar entre 12:00 e 13:00.'
    if is_lunch_boundary_time(end_time):
        errors['end_time'] = 'A aula/horário não pode terminar entre 12:00 e 13:00.'
    return errors


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
                and 'opportunit' not in accessor_lower
                and 'oportunidade' not in accessor_lower
                and 'lead' not in accessor_lower
                and 'funnel' not in related_name
                and 'funil' not in related_name
                and 'opportunit' not in related_name
                and 'oportunidade' not in related_name
                and 'lead' not in related_name
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

    @property
    def requires_trial_lesson(self):
        text = slugify(f'{self.code} {self.name}')
        has_trial = 'experimental' in text or 'experiental' in text
        has_scheduled = 'agendada' in text or 'agendado' in text
        is_standard_trial_stage = text.startswith('3-') and 'aula' in text and has_trial
        return 'aula' in text and has_trial and (has_scheduled or is_standard_trial_stage)

    def has_usage(self):
        return self.legacy_funnel_models.exists() or self.opportunities.exists()

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
        return self.legacy_funnel_models.exists() or self.opportunities.exists()

    def can_be_deleted(self):
        return not self.has_usage()


class FunnelModel(models.Model):
    """Modelo que define os campos usados para criar funis comerciais."""

    name = models.CharField('Nome do modelo', max_length=160, default='')
    funnel_type = models.ForeignKey(
        FunnelType,
        on_delete=models.PROTECT,
        related_name='legacy_funnel_models',
        verbose_name='Tipo legado',
        null=True,
        blank=True,
    )
    stage = models.ForeignKey(
        FunnelStage,
        on_delete=models.PROTECT,
        related_name='legacy_funnel_models',
        verbose_name='Etapa legada',
        null=True,
        blank=True,
    )
    origin = models.ForeignKey(
        OpportunityOrigin,
        on_delete=models.PROTECT,
        related_name='legacy_funnel_models',
        verbose_name='Origem legada',
        null=True,
        blank=True,
    )
    responsible_name = models.CharField('Nome do responsável legado', max_length=120, blank=True)
    responsible_phone = models.CharField('Telefone do responsável legado', max_length=30, blank=True)
    active = models.BooleanField('Ativado', default=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Modelo de funil'
        verbose_name_plural = 'Modelos de funis'

    def __str__(self):
        if self.name:
            return self.name
        parts = [
            getattr(self.funnel_type, 'name', ''),
            getattr(self.stage, 'name', ''),
            self.responsible_name,
        ]
        label = ' - '.join(part for part in parts if part)
        return label or f'Modelo de funil {self.pk}'

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

    def has_opportunity_usage(self):
        if not self.pk or not self.funnel_model_id:
            return False
        return CommercialOpportunity.objects.filter(
            commercial_funnel__funnel_model_id=self.funnel_model_id,
        ).exists()

    def delete(self, *args, **kwargs):
        if self.has_opportunity_usage():
            raise ProtectedError(
                'Campos adicionais de modelos que ja possuem oportunidades nao podem ser removidos.',
                [self],
            )
        return super().delete(*args, **kwargs)


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


class CommercialOpportunity(models.Model):
    """Entrada/lead acompanhado dentro de um funil comercial."""

    INTEREST_PARTNERSHIP = 'partnership'
    INTEREST_PRODUCT = 'product'
    INTEREST_EVENT = 'event'
    INTEREST_OTHER = 'other'
    INTEREST_TYPE_CHOICES = [
        (INTEREST_PARTNERSHIP, 'Parceria'),
        (INTEREST_PRODUCT, 'Produto'),
        (INTEREST_EVENT, 'Evento'),
        (INTEREST_OTHER, 'Outros'),
    ]

    title = models.CharField('Oportunidade', max_length=160)
    commercial_funnel = models.ForeignKey(CommercialFunnel, on_delete=models.PROTECT, related_name='opportunities', verbose_name='Funil')
    funnel_type = models.ForeignKey(FunnelType, on_delete=models.PROTECT, related_name='opportunities', verbose_name='Tipo', null=True, blank=True)
    stage = models.ForeignKey(FunnelStage, on_delete=models.PROTECT, related_name='opportunities', verbose_name='Etapa', null=True, blank=True)
    origin = models.ForeignKey(OpportunityOrigin, on_delete=models.PROTECT, related_name='opportunities', verbose_name='Origem', null=True, blank=True)
    interest_course = models.ForeignKey('Course', on_delete=models.PROTECT, related_name='commercial_opportunities', verbose_name='Interesse em curso', null=True, blank=True)
    interest_type = models.CharField('Tipo de interesse', max_length=30, choices=INTEREST_TYPE_CHOICES, blank=True)
    value = models.DecimalField('Valor', max_digits=10, decimal_places=2, null=True, blank=True)
    contact_name = models.CharField('Nome do responsável', max_length=120)
    contact_phone = models.CharField('Telefone do responsável', max_length=30)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_commercial_opportunities', verbose_name='Atendente responsável')
    next_follow_up_date = models.DateField('Data próx. Follow-Up')
    field_values = models.JSONField('Campos adicionais preenchidos', default=dict, blank=True)
    notes = models.TextField('Observações', blank=True)
    automation_key = models.CharField('Chave de automação', max_length=160, blank=True, db_index=True)
    active = models.BooleanField('Ativa', default=True)
    created_at = models.DateTimeField('Data de criação da oportunidade', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizada em', auto_now=True)

    class Meta:
        ordering = [
            'funnel_type__name',
            'stage__order',
            'stage__name',
            'title',
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['automation_key'],
                condition=~models.Q(automation_key=''),
                name='unique_commercial_opportunity_automation_key',
            ),
        ]
        verbose_name = 'Oportunidade comercial'
        verbose_name_plural = 'Oportunidades comerciais'

    def __str__(self):
        return self.title

    @property
    def funnel_model(self):
        return self.commercial_funnel.funnel_model

    @property
    def interest_label(self):
        if self.interest_course_id:
            return self.interest_course.name
        if self.interest_type:
            return self.get_interest_type_display()
        return ''


class CommercialOpportunityFollowUp(models.Model):
    """Histórico de alterações da próxima data de follow-up da oportunidade."""

    opportunity = models.ForeignKey(CommercialOpportunity, on_delete=models.CASCADE, related_name='follow_up_events', verbose_name='Oportunidade')
    previous_date = models.DateField('Data anterior', null=True, blank=True)
    scheduled_date = models.DateField('Nova data de follow-up')
    note = models.TextField('Observação', blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='commercial_follow_up_events', verbose_name='Usuário')
    created_at = models.DateTimeField('Registrado em', auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Histórico de follow-up comercial'
        verbose_name_plural = 'Históricos de follow-up comercial'

    def __str__(self):
        return f'{self.opportunity} - {self.scheduled_date}'


class CommercialOpportunityStageEvent(models.Model):
    """Histórico de alterações de etapa da oportunidade comercial."""

    opportunity = models.ForeignKey(CommercialOpportunity, on_delete=models.CASCADE, related_name='stage_events', verbose_name='Oportunidade')
    previous_stage = models.ForeignKey(FunnelStage, on_delete=models.SET_NULL, null=True, blank=True, related_name='commercial_stage_events_from', verbose_name='Etapa anterior')
    new_stage = models.ForeignKey(FunnelStage, on_delete=models.SET_NULL, null=True, blank=True, related_name='commercial_stage_events_to', verbose_name='Nova etapa')
    previous_stage_label = models.CharField('Nome da etapa anterior', max_length=120, blank=True)
    new_stage_label = models.CharField('Nome da nova etapa', max_length=120, blank=True)
    note = models.TextField('Observação', blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='commercial_stage_events', verbose_name='Usuário')
    created_at = models.DateTimeField('Registrado em', auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['opportunity', 'created_at'], name='chk_stageevt_opp_created_idx'),
            models.Index(fields=['new_stage', 'created_at'], name='chk_stageevt_new_created_idx'),
        ]
        verbose_name = 'Histórico de etapa comercial'
        verbose_name_plural = 'Históricos de etapas comerciais'

    def __str__(self):
        return f'{self.opportunity} - {self.previous_stage_label or "-"} -> {self.new_stage_label or "-"}'


class Course(models.Model):
    """Curso pedagógico administrado internamente."""

    SOURCE_LOCAL = 'local'
    SOURCE_SPONTE = 'sponte'
    SOURCE_CHOICES = [
        (SOURCE_LOCAL, 'Checklist'),
        (SOURCE_SPONTE, 'Sponte'),
    ]

    name = models.CharField('Nome', max_length=160, unique=True)
    description = models.TextField('Descrição', blank=True)
    value = models.DecimalField('Valor', max_digits=10, decimal_places=2)
    kit_quantity = models.PositiveIntegerField('Quantidade de kits', default=1)
    max_students_per_slot = models.PositiveIntegerField('Máximo de alunos por horário', null=True, blank=True)
    active = models.BooleanField('Ativo', default=True)
    source = models.CharField('Origem', max_length=30, choices=SOURCE_CHOICES, default=SOURCE_LOCAL)
    external_id = models.CharField('ID externo', max_length=120, blank=True)
    synced_at = models.DateTimeField('Sincronizado em', null=True, blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'],
                condition=~models.Q(external_id=''),
                name='unique_course_source_external',
            ),
        ]
        verbose_name = 'Curso'
        verbose_name_plural = 'Cursos'

    def __str__(self):
        return self.name


class Room(models.Model):
    """Sala disponível para aulas pedagógicas."""

    name = models.CharField('Nome', max_length=120, unique=True)
    capacity = models.PositiveIntegerField('Capacidade', default=1)
    active = models.BooleanField('Ativa', default=True)
    created_at = models.DateTimeField('Criada em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizada em', auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Sala'
        verbose_name_plural = 'Salas'

    def __str__(self):
        return self.name


class TimeSlot(models.Model):
    """Horário padrão usado na agenda pedagógica."""

    WEEKDAY_CHOICES = [
        (0, 'Segunda-feira'),
        (1, 'Terça-feira'),
        (2, 'Quarta-feira'),
        (3, 'Quinta-feira'),
        (4, 'Sexta-feira'),
        (5, 'Sábado'),
    ]

    weekday = models.IntegerField('Dia da semana', choices=WEEKDAY_CHOICES)
    start_time = models.TimeField('Início')
    end_time = models.TimeField('Fim')
    active = models.BooleanField('Ativo', default=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['weekday', 'start_time', 'end_time']
        constraints = [
            models.UniqueConstraint(fields=['weekday', 'start_time', 'end_time'], name='unique_pedagogical_timeslot'),
        ]
        verbose_name = 'Horário pedagógico'
        verbose_name_plural = 'Horários pedagógicos'

    def __str__(self):
        return f'{self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}'

    def clean(self):
        errors = lunch_boundary_errors(self.start_time, self.end_time)
        if self.start_time and self.end_time:
            if self.start_time >= self.end_time:
                errors['end_time'] = 'A hora fim deve ser maior que a hora de início.'
            else:
                duration = (
                    datetime.combine(timezone.localdate(), self.end_time)
                    - datetime.combine(timezone.localdate(), self.start_time)
                ).total_seconds() / 3600
                if duration > 2:
                    errors['end_time'] = 'Horários pedagógicos podem durar no máximo 2 horas.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SchoolHoliday(models.Model):
    """Feriado ou recesso que bloqueia agendamentos pedagógicos."""

    KIND_NATIONAL = 'national_holiday'
    KIND_INSTITUTIONAL = 'institutional_holiday'
    KIND_RECESS = 'recess'
    KIND_CHOICES = [
        (KIND_NATIONAL, 'Feriado nacional'),
        (KIND_INSTITUTIONAL, 'Feriado institucional'),
        (KIND_RECESS, 'Recesso'),
    ]

    start_date = models.DateField('Data inicial')
    end_date = models.DateField('Data final')
    kind = models.CharField('Tipo', max_length=30, choices=KIND_CHOICES, default=KIND_INSTITUTIONAL)
    description = models.CharField('Descrição', max_length=180)
    active = models.BooleanField('Ativo', default=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['start_date', 'description']
        verbose_name = 'Feriado/Recesso'
        verbose_name_plural = 'Feriados/Recessos'

    def __str__(self):
        return f'{self.description} ({self.start_date:%d/%m/%Y} a {self.end_date:%d/%m/%Y})'


class PedagogicalStudent(models.Model):
    """Aluno matriculado disponível para agendamento de aulas regulares."""

    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Ativo'),
        (STATUS_INACTIVE, 'Desativado'),
    ]

    name = models.CharField('Nome', max_length=160)
    enrollment_number = models.CharField('Matrícula', max_length=80, blank=True)
    responsible_name = models.CharField('Responsável', max_length=160, blank=True)
    whatsapp = models.CharField('WhatsApp', max_length=30, blank=True)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    source = models.CharField('Origem', max_length=80, blank=True)
    external_id = models.CharField('ID externo', max_length=120, blank=True)
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['enrollment_number'],
                condition=~models.Q(enrollment_number=''),
                name='unique_pedagogical_student_enrollment',
            ),
        ]
        verbose_name = 'Aluno pedagógico'
        verbose_name_plural = 'Alunos pedagógicos'

    def __str__(self):
        return self.name

    @property
    def active(self):
        return self.status == self.STATUS_ACTIVE


class Lesson(models.Model):
    """Aula regular ou experimental na agenda pedagógica."""

    SOURCE_LOCAL = 'local'
    SOURCE_SPONTE = 'sponte'
    SOURCE_CHOICES = [
        (SOURCE_LOCAL, 'Checklist'),
        (SOURCE_SPONTE, 'Sponte'),
    ]

    TYPE_REGULAR = 'regular'
    TYPE_TRIAL = 'trial'
    TYPE_CHOICES = [
        (TYPE_REGULAR, 'Matriculado'),
        (TYPE_TRIAL, 'Experimental ou Play'),
    ]

    TRIAL_KIND_EXPERIMENTAL = 'experimental'
    TRIAL_KIND_PLAY = 'play'
    TRIAL_KIND_CHOICES = [
        (TRIAL_KIND_EXPERIMENTAL, 'Experimental'),
        (TRIAL_KIND_PLAY, 'Play'),
    ]

    STATUS_DONE = 'done'
    STATUS_ABSENT = 'absent'
    STATUS_NOT_GIVEN = 'not_given'
    STATUS_CANCELLED = 'cancelled'
    # Backward-compatible aliases for older code/tests and pre-0036 rows.
    STATUS_SCHEDULED = STATUS_NOT_GIVEN
    STATUS_RESCHEDULED = STATUS_CANCELLED
    STATUS_CHOICES = [
        (STATUS_DONE, 'Presença'),
        (STATUS_ABSENT, 'Falta'),
        (STATUS_NOT_GIVEN, 'Não dada'),
        (STATUS_CANCELLED, 'Cancelada'),
    ]
    OCCUPYING_STATUSES = [STATUS_DONE, STATUS_ABSENT, STATUS_NOT_GIVEN]

    student = models.ForeignKey(PedagogicalStudent, on_delete=models.PROTECT, related_name='lessons', verbose_name='Aluno', null=True, blank=True)
    student_name_snapshot = models.CharField('Nome do aluno/interessado', max_length=160, blank=True)
    responsible_name_snapshot = models.CharField('Responsável', max_length=160, blank=True)
    whatsapp_snapshot = models.CharField('WhatsApp', max_length=30, blank=True)
    lesson_type = models.CharField('Tipo', max_length=20, choices=TYPE_CHOICES, default=TYPE_REGULAR)
    trial_kind = models.CharField('Tipo de aula experimental ou Play', max_length=20, choices=TRIAL_KIND_CHOICES, blank=True)
    commercial_opportunity = models.ForeignKey(CommercialOpportunity, on_delete=models.PROTECT, related_name='trial_lessons', verbose_name='Oportunidade', null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='lessons', verbose_name='Curso', null=True, blank=True)
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name='lessons', verbose_name='Sala')
    date = models.DateField('Data')
    start_time = models.TimeField('Início')
    end_time = models.TimeField('Fim')
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default=STATUS_NOT_GIVEN)
    notes = models.TextField('Observação', blank=True)
    source = models.CharField('Origem', max_length=30, choices=SOURCE_CHOICES, default=SOURCE_LOCAL)
    external_id = models.CharField('ID externo', max_length=160, blank=True)
    synced_at = models.DateTimeField('Sincronizada em', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedagogical_lessons_created', verbose_name='Criado por')
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['date', 'start_time', 'room__name', 'student_name_snapshot']
        indexes = [
            models.Index(fields=['date', 'start_time', 'end_time'], name='lesson_date_time_idx'),
            models.Index(fields=['course', 'date', 'start_time'], name='lesson_course_date_idx'),
            models.Index(fields=['room', 'date', 'start_time'], name='lesson_room_date_idx'),
            models.Index(fields=['source', 'external_id'], name='lesson_source_external_idx'),
            models.Index(fields=['commercial_opportunity', 'date'], name='lesson_opp_date_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'],
                condition=~models.Q(external_id=''),
                name='unique_lesson_source_external',
            ),
        ]
        verbose_name = 'Aula'
        verbose_name_plural = 'Aulas'

    def __str__(self):
        course_label = self.course if self.course_id else 'Curso a definir'
        return f'{self.student_name_snapshot} - {course_label} - {self.date:%d/%m/%Y} {self.start_time:%H:%M}'

    def _duration_hours(self):
        if not self.date or not self.start_time or not self.end_time:
            return None
        start = datetime.combine(self.date, self.start_time)
        end = datetime.combine(self.date, self.end_time)
        return (end - start).total_seconds() / 3600

    def _overlapping_lessons(self):
        if not self.date or not self.start_time or not self.end_time:
            return Lesson.objects.none()
        lessons = Lesson.objects.filter(
            date=self.date,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
            status__in=self.OCCUPYING_STATUSES,
        )
        if self.pk:
            lessons = lessons.exclude(pk=self.pk)
        return lessons

    @property
    def is_sponte_synced(self):
        return self.source == self.SOURCE_SPONTE

    def assistant_warning_message(self):
        if self.status not in self.OCCUPYING_STATUSES:
            return ''
        total = self._overlapping_lessons().count() + 1
        if total >= 3:
            return 'Atenção: este horário terá 3 ou mais alunos/aulas. É recomendável ter um assistente para apoiar o instrutor.'
        return ''

    def clean(self):
        errors = {}
        if self.start_time and self.end_time:
            if not self.is_sponte_synced:
                errors.update(lunch_boundary_errors(self.start_time, self.end_time))
            if self.start_time >= self.end_time:
                errors['end_time'] = 'A hora fim deve ser maior que a hora de início.'
            elif not self.is_sponte_synced and self._duration_hours() is not None and self._duration_hours() > 2:
                errors['end_time'] = 'A aula pode durar no máximo 2 horas.'

        if self.lesson_type == self.TYPE_REGULAR and not self.student_id:
            errors['student'] = 'Selecione um aluno para aula de matriculado.'
        if self.lesson_type == self.TYPE_REGULAR and not self.course_id:
            errors['course'] = 'Selecione um curso para aula de matriculado.'
        if self.lesson_type == self.TYPE_TRIAL:
            if not self.trial_kind:
                errors['trial_kind'] = 'Informe se a aula é Experimental ou Play.'
            if not self.commercial_opportunity_id:
                errors['commercial_opportunity'] = 'Vincule a aula a uma oportunidade comercial.'
            if not (self.student_name_snapshot or '').strip() and not self.commercial_opportunity_id:
                errors['student_name_snapshot'] = 'Informe o nome do interessado.'

        if errors:
            raise ValidationError(errors)

        overlapping = self._overlapping_lessons()
        if self.status in self.OCCUPYING_STATUSES and not self.is_sponte_synced:
            if SchoolHoliday.objects.filter(active=True, start_date__lte=self.date, end_date__gte=self.date).exists():
                errors['date'] = 'Não é permitido agendar aulas em feriado ou recesso.'

            if self.course_id and self.course and overlapping.filter(course_id=self.course_id).count() >= self.course.kit_quantity:
                errors['course'] = 'Não há kits disponíveis para este curso neste dia e horário.'

            if self.room_id and self.room and overlapping.filter(room_id=self.room_id).count() >= self.room.capacity:
                errors['room'] = 'Não há vagas disponíveis nesta sala neste dia e horário.'

            if self.student_id and overlapping.filter(student_id=self.student_id).exists():
                errors['student'] = 'Este aluno já possui aula neste dia e horário.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.student_id:
            self.student_name_snapshot = self.student.name
            self.responsible_name_snapshot = self.student.responsible_name
            self.whatsapp_snapshot = self.student.whatsapp
        elif self.commercial_opportunity_id:
            if not self.student_name_snapshot:
                self.student_name_snapshot = self.commercial_opportunity.title
            if not self.responsible_name_snapshot:
                self.responsible_name_snapshot = self.commercial_opportunity.contact_name
            if not self.whatsapp_snapshot:
                self.whatsapp_snapshot = self.commercial_opportunity.contact_phone
        self.full_clean()
        return super().save(*args, **kwargs)


class LessonFeedback(models.Model):
    """Feedback pedagógico preenchido após uma aula regular de aluno matriculado."""

    SCORE_CHOICES = [(score, str(score)) for score in range(0, 11)]
    MODULE_CHOICES = [(number, str(number)) for number in range(1, 4)]
    LESSON_NUMBER_CHOICES = [(number, str(number)) for number in range(1, 16)]
    PUNCTUALITY_CHOICES = [
        (10, 'Sim'),
        (5, 'Não'),
    ]

    lesson = models.OneToOneField(Lesson, on_delete=models.PROTECT, related_name='feedback', verbose_name='Aula')
    module_number = models.PositiveSmallIntegerField('Módulo', choices=MODULE_CHOICES)
    lesson_number = models.PositiveSmallIntegerField('Aula', choices=LESSON_NUMBER_CHOICES)
    punctuality_score = models.PositiveSmallIntegerField('Pontualidade', choices=PUNCTUALITY_CHOICES)
    assembly_comment = models.TextField('Montagem')
    assembly_score = models.PositiveSmallIntegerField('Montagem nota', choices=SCORE_CHOICES)
    has_programming = models.BooleanField('A aula teve programação?', default=False)
    programming_comment = models.TextField('Programação', blank=True)
    programming_score = models.PositiveSmallIntegerField('Programação nota', choices=SCORE_CHOICES, null=True, blank=True)
    participation_comment = models.TextField('Interesse/Participação')
    participation_score = models.PositiveSmallIntegerField('Interesse/Participação nota', choices=SCORE_CHOICES)
    behavior_comment = models.TextField('Comportamento')
    behavior_score = models.PositiveSmallIntegerField('Comportamento nota', choices=SCORE_CHOICES)
    general_comment = models.TextField('Comentário geral')
    general_score = models.DecimalField('Comentário geral nota', max_digits=4, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='lesson_feedbacks_created', verbose_name='Criado por')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='lesson_feedbacks_updated', verbose_name='Atualizado por')
    created_at = models.DateTimeField('Criado em', auto_now_add=True)
    updated_at = models.DateTimeField('Atualizado em', auto_now=True)

    class Meta:
        ordering = ['-lesson__date', '-lesson__start_time']
        verbose_name = 'Feedback de aula'
        verbose_name_plural = 'Feedbacks de aula'

    def __str__(self):
        return f'Feedback - {self.lesson}'

    def _score_values(self):
        values = [
            self.punctuality_score,
            self.assembly_score,
            self.participation_score,
            self.behavior_score,
        ]
        if self.has_programming:
            values.append(self.programming_score)
        return [score for score in values if score is not None]

    def calculate_general_score(self):
        values = self._score_values()
        if not values:
            return Decimal('0.00')
        average = Decimal(sum(values)) / Decimal(len(values))
        return average.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def clean(self):
        errors = {}
        if self.lesson_id and self.lesson.lesson_type != Lesson.TYPE_REGULAR:
            errors['lesson'] = 'Feedback de aula é permitido apenas para aulas de aluno matriculado.'
        if self.has_programming:
            if not (self.programming_comment or '').strip():
                errors['programming_comment'] = 'Informe o comentário de programação.'
            if self.programming_score is None:
                errors['programming_score'] = 'Informe a nota de programação.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.has_programming:
            self.programming_comment = ''
            self.programming_score = None
        self.general_score = self.calculate_general_score()
        self.full_clean()
        return super().save(*args, **kwargs)


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
