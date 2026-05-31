# Generated manually for My Robot Checklist System.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Position',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=80, unique=True, verbose_name='Código')),
                ('name', models.CharField(max_length=140, unique=True, verbose_name='Cargo')),
                ('description', models.TextField(blank=True, verbose_name='Descrição')),
                ('active', models.BooleanField(default=True, verbose_name='Ativo')),
            ],
            options={'verbose_name': 'Cargo', 'verbose_name_plural': 'Cargos', 'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('display_name', models.CharField(max_length=120, verbose_name='Nome de exibição')),
                ('system_role', models.CharField(choices=[('ADMIN', 'Administrador'), ('OPERATOR', 'Operacional')], default='OPERATOR', max_length=20, verbose_name='Perfil')),
                ('active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('position', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='users', to='checklists.position')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'Perfil de usuário', 'verbose_name_plural': 'Perfis de usuário'},
        ),
        migrations.CreateModel(
            name='TaskTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255, verbose_name='Tarefa')),
                ('description', models.TextField(blank=True, verbose_name='Instruções')),
                ('frequency', models.CharField(choices=[('DAILY', 'Diária'), ('WEEKLY', 'Semanal'), ('BIWEEKLY', 'Quinzenal'), ('MONTHLY', 'Mensal'), ('CONDITIONAL', 'Condicional')], default='DAILY', max_length=20, verbose_name='Frequência')),
                ('day_of_week', models.IntegerField(choices=[(0, 'Segunda-feira'), (1, 'Terça-feira'), (2, 'Quarta-feira'), (3, 'Quinta-feira'), (4, 'Sexta-feira')], default=0, verbose_name='Dia da semana')),
                ('start_time', models.TimeField(blank=True, null=True, verbose_name='Início previsto')),
                ('end_time', models.TimeField(blank=True, null=True, verbose_name='Fim previsto')),
                ('category', models.CharField(blank=True, max_length=120, verbose_name='Categoria')),
                ('evidence_required', models.CharField(blank=True, max_length=255, verbose_name='Evidência esperada')),
                ('monthly_goal', models.CharField(blank=True, max_length=255, verbose_name='Meta mensal relacionada')),
                ('source', models.CharField(default='Checklist REV06', max_length=120, verbose_name='Origem')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Ordem')),
                ('active', models.BooleanField(default=True, verbose_name='Ativa')),
                ('position', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='task_templates', to='checklists.position')),
            ],
            options={'verbose_name': 'Modelo de tarefa', 'verbose_name_plural': 'Modelos de tarefa', 'ordering': ['position__name', 'day_of_week', 'order', 'start_time', 'title']},
        ),
        migrations.CreateModel(
            name='ChecklistOccurrence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Data')),
                ('status', models.CharField(choices=[('PLANNED', 'Previsto'), ('IN_PROGRESS', 'Em andamento'), ('DONE', 'Concluído'), ('NOT_APPLICABLE', 'Não se aplica'), ('BLOCKED', 'Bloqueado/Pendente')], default='PLANNED', max_length=20, verbose_name='Status')),
                ('evidence_text', models.TextField(blank=True, verbose_name='Evidência/observação')),
                ('evidence_file', models.FileField(blank=True, null=True, upload_to='evidencias/%Y/%m/', verbose_name='Arquivo de evidência')),
                ('blocked_reason', models.TextField(blank=True, verbose_name='Motivo de pendência/bloqueio')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('completed_at', models.DateTimeField(blank=True, null=True, verbose_name='Concluído em')),
                ('position', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='occurrences', to='checklists.position')),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='occurrences', to='checklists.tasktemplate')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_occurrences', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'Execução de tarefa', 'verbose_name_plural': 'Execuções de tarefas', 'ordering': ['date', 'position__name', 'template__order', 'template__start_time', 'template__title'], 'unique_together': {('template', 'position', 'date')}},
        ),
        migrations.CreateModel(
            name='DailyNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Data')),
                ('notes', models.TextField(blank=True, verbose_name='Resumo do dia')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('position', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_notes', to='checklists.position')),
            ],
            options={'verbose_name': 'Resumo diário', 'verbose_name_plural': 'Resumos diários', 'ordering': ['-date', 'position__name'], 'unique_together': {('position', 'date')}},
        ),
        migrations.CreateModel(
            name='MetricType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=80, unique=True, verbose_name='Código')),
                ('name', models.CharField(max_length=140, verbose_name='Indicador')),
                ('monthly_target', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Meta mensal')),
                ('unit', models.CharField(default='un', max_length=40, verbose_name='Unidade')),
                ('active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('position', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='metric_types', to='checklists.position')),
            ],
            options={'verbose_name': 'Indicador', 'verbose_name_plural': 'Indicadores', 'ordering': ['position__name', 'name']},
        ),
        migrations.CreateModel(
            name='MetricRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Data')),
                ('value', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='Valor')),
                ('notes', models.TextField(blank=True, verbose_name='Observações')),
                ('evidence_file', models.FileField(blank=True, null=True, upload_to='metricas/%Y/%m/', verbose_name='Arquivo de evidência')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('metric', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='records', to='checklists.metrictype')),
                ('position', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='metric_records', to='checklists.position')),
            ],
            options={'verbose_name': 'Registro de indicador', 'verbose_name_plural': 'Registros de indicadores', 'ordering': ['-date', 'metric__name']},
        ),
        migrations.CreateModel(
            name='ActivityLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(max_length=120, verbose_name='Ação')),
                ('object_type', models.CharField(blank=True, max_length=80, verbose_name='Tipo de objeto')),
                ('object_id', models.CharField(blank=True, max_length=80, verbose_name='ID do objeto')),
                ('details', models.TextField(blank=True, verbose_name='Detalhes')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('position', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='checklists.position')),
            ],
            options={'verbose_name': 'Log de atividade', 'verbose_name_plural': 'Logs de atividade', 'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='checklistoccurrence',
            index=models.Index(fields=['date', 'position', 'status'], name='checklists_c_date_3e8c3d_idx'),
        ),
        migrations.AddIndex(
            model_name='checklistoccurrence',
            index=models.Index(fields=['position', 'status'], name='checklists_c_positio_6e83fe_idx'),
        ),
    ]
