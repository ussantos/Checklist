from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0045_rename_won_stage'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SponteSyncJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('students', 'Alunos'), ('courses', 'Cursos'), ('schedule', 'Agenda'), ('instructor_schedule', 'Agenda do instrutor')], max_length=40, verbose_name='Tipo de sincronização')),
                ('status', models.CharField(choices=[('queued', 'Na fila'), ('running', 'Em execução'), ('succeeded', 'Concluída'), ('failed', 'Falhou')], default='queued', max_length=20, verbose_name='Status')),
                ('period_start', models.DateField(blank=True, null=True, verbose_name='Início do período')),
                ('period_end', models.DateField(blank=True, null=True, verbose_name='Fim do período')),
                ('allow_past', models.BooleanField(default=False, verbose_name='Permite período passado')),
                ('result', models.JSONField(blank=True, default=dict, verbose_name='Resultado')),
                ('error_message', models.TextField(blank=True, verbose_name='Erro')),
                ('started_at', models.DateTimeField(blank=True, null=True, verbose_name='Iniciado em')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='Finalizado em')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('requested_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sponte_sync_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Job de sincronização Sponte',
                'verbose_name_plural': 'Jobs de sincronização Sponte',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='spontesyncjob',
            index=models.Index(fields=['requested_by', 'status', 'created_at'], name='spontejob_user_status_created'),
        ),
        migrations.AddIndex(
            model_name='spontesyncjob',
            index=models.Index(fields=['kind', 'status', 'created_at'], name='spontejob_kind_status_created'),
        ),
    ]
