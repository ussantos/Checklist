# Generated manually for Checklist on 2026-06-29

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def initialize_stage_events(apps, schema_editor):
    CommercialOpportunity = apps.get_model('checklists', 'CommercialOpportunity')
    CommercialOpportunityStageEvent = apps.get_model('checklists', 'CommercialOpportunityStageEvent')

    for opportunity in CommercialOpportunity.objects.select_related('stage').all():
        stage = opportunity.stage
        CommercialOpportunityStageEvent.objects.create(
            opportunity=opportunity,
            previous_stage=None,
            new_stage=stage,
            previous_stage_label='',
            new_stage_label=stage.name if stage else '',
            note='Etapa inicial registrada durante a migração do histórico de etapas.',
            actor=None,
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('checklists', '0022_alter_commercialopportunity_created_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommercialOpportunityStageEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('previous_stage_label', models.CharField(blank=True, max_length=120, verbose_name='Nome da etapa anterior')),
                ('new_stage_label', models.CharField(blank=True, max_length=120, verbose_name='Nome da nova etapa')),
                ('note', models.TextField(blank=True, verbose_name='Observação')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Registrado em')),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='commercial_stage_events', to=settings.AUTH_USER_MODEL, verbose_name='Usuário')),
                ('new_stage', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='commercial_stage_events_to', to='checklists.funnelstage', verbose_name='Nova etapa')),
                ('opportunity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stage_events', to='checklists.commercialopportunity', verbose_name='Oportunidade')),
                ('previous_stage', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='commercial_stage_events_from', to='checklists.funnelstage', verbose_name='Etapa anterior')),
            ],
            options={
                'verbose_name': 'Histórico de etapa comercial',
                'verbose_name_plural': 'Históricos de etapas comerciais',
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['opportunity', 'created_at'], name='chk_stageevt_opp_created_idx'),
                    models.Index(fields=['new_stage', 'created_at'], name='chk_stageevt_new_created_idx'),
                ],
            },
        ),
        migrations.RunPython(initialize_stage_events, migrations.RunPython.noop),
    ]
