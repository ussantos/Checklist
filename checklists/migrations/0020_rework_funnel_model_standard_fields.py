# Generated manually for Checklist on 2026-06-29

import django.db.models.deletion
from django.db import migrations, models


def migrate_existing_commercial_data(apps, schema_editor):
    FunnelModel = apps.get_model('checklists', 'FunnelModel')
    CommercialOpportunity = apps.get_model('checklists', 'CommercialOpportunity')

    for funnel_model in FunnelModel.objects.select_related('funnel_type', 'stage').all():
        if funnel_model.name:
            continue
        parts = [
            getattr(funnel_model.funnel_type, 'name', ''),
            getattr(funnel_model.stage, 'name', ''),
            funnel_model.responsible_name,
        ]
        funnel_model.name = ' - '.join(part for part in parts if part) or f'Modelo de funil {funnel_model.pk}'
        funnel_model.save(update_fields=['name'])

    opportunities = CommercialOpportunity.objects.select_related(
        'commercial_funnel__funnel_model',
    )
    for opportunity in opportunities:
        funnel_model = opportunity.commercial_funnel.funnel_model
        opportunity.funnel_type_id = funnel_model.funnel_type_id
        opportunity.stage_id = funnel_model.stage_id
        opportunity.origin_id = funnel_model.origin_id
        opportunity.save(update_fields=['funnel_type', 'stage', 'origin'])


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0019_commercialopportunity'),
    ]

    operations = [
        migrations.AddField(
            model_name='funnelmodel',
            name='name',
            field=models.CharField(default='', max_length=160, verbose_name='Nome do modelo'),
        ),
        migrations.AddField(
            model_name='commercialopportunity',
            name='funnel_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='opportunities', to='checklists.funneltype', verbose_name='Tipo'),
        ),
        migrations.AddField(
            model_name='commercialopportunity',
            name='origin',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='opportunities', to='checklists.opportunityorigin', verbose_name='Origem'),
        ),
        migrations.AddField(
            model_name='commercialopportunity',
            name='stage',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='opportunities', to='checklists.funnelstage', verbose_name='Etapa'),
        ),
        migrations.RunPython(migrate_existing_commercial_data, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='funnelmodel',
            name='funnel_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='legacy_funnel_models', to='checklists.funneltype', verbose_name='Tipo legado'),
        ),
        migrations.AlterField(
            model_name='funnelmodel',
            name='origin',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='legacy_funnel_models', to='checklists.opportunityorigin', verbose_name='Origem legada'),
        ),
        migrations.AlterField(
            model_name='funnelmodel',
            name='responsible_name',
            field=models.CharField(blank=True, max_length=120, verbose_name='Nome do responsável legado'),
        ),
        migrations.AlterField(
            model_name='funnelmodel',
            name='responsible_phone',
            field=models.CharField(blank=True, max_length=30, verbose_name='Telefone do responsável legado'),
        ),
        migrations.AlterField(
            model_name='funnelmodel',
            name='stage',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='legacy_funnel_models', to='checklists.funnelstage', verbose_name='Etapa legada'),
        ),
        migrations.AlterModelOptions(
            name='commercialopportunity',
            options={
                'ordering': ['funnel_type__name', 'stage__order', 'stage__name', 'title'],
                'verbose_name': 'Oportunidade comercial',
                'verbose_name_plural': 'Oportunidades comerciais',
            },
        ),
        migrations.AlterModelOptions(
            name='funnelmodel',
            options={
                'ordering': ['name'],
                'verbose_name': 'Modelo de funil',
                'verbose_name_plural': 'Modelos de funis',
            },
        ),
    ]
