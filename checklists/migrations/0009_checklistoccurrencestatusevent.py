from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def create_initial_status_events(apps, schema_editor):
    ChecklistOccurrence = apps.get_model('checklists', 'ChecklistOccurrence')
    ChecklistOccurrenceStatusEvent = apps.get_model('checklists', 'ChecklistOccurrenceStatusEvent')
    events = []
    for occurrence in ChecklistOccurrence.objects.all().iterator():
        events.append(ChecklistOccurrenceStatusEvent(
            occurrence_id=occurrence.id,
            previous_status='',
            new_status=occurrence.status,
            changed_by_id=occurrence.updated_by_id,
            changed_at=occurrence.created_at,
        ))
    ChecklistOccurrenceStatusEvent.objects.bulk_create(events, batch_size=1000)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('checklists', '0008_tasktemplate_requires_evidence'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChecklistOccurrenceStatusEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('previous_status', models.CharField(blank=True, choices=[('PLANNED', 'Previsto'), ('IN_PROGRESS', 'Em andamento'), ('DONE', 'Concluído'), ('NOT_APPLICABLE', 'Não se aplica'), ('BLOCKED', 'Bloqueado/Pendente')], max_length=20, verbose_name='Status anterior')),
                ('new_status', models.CharField(choices=[('PLANNED', 'Previsto'), ('IN_PROGRESS', 'Em andamento'), ('DONE', 'Concluído'), ('NOT_APPLICABLE', 'Não se aplica'), ('BLOCKED', 'Bloqueado/Pendente')], max_length=20, verbose_name='Novo status')),
                ('changed_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Alterado em')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Registrado em')),
                ('changed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='checklist_status_events', to=settings.AUTH_USER_MODEL)),
                ('occurrence', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='status_events', to='checklists.checklistoccurrence')),
            ],
            options={
                'verbose_name': 'Evento de status de atividade',
                'verbose_name_plural': 'Eventos de status de atividades',
                'ordering': ['changed_at', 'id'],
            },
        ),
        migrations.AddIndex(
            model_name='checklistoccurrencestatusevent',
            index=models.Index(fields=['occurrence', 'changed_at'], name='checklists__occur_3b542f_idx'),
        ),
        migrations.AddIndex(
            model_name='checklistoccurrencestatusevent',
            index=models.Index(fields=['changed_at'], name='checklists__changed_f98612_idx'),
        ),
        migrations.AddIndex(
            model_name='checklistoccurrencestatusevent',
            index=models.Index(fields=['new_status'], name='checklists__new_sta_8b576e_idx'),
        ),
        migrations.RunPython(create_initial_status_events, migrations.RunPython.noop),
    ]
