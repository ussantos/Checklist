# Generated manually for Checklist on 2026-06-29

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def initialize_follow_up_dates(apps, schema_editor):
    CommercialOpportunity = apps.get_model('checklists', 'CommercialOpportunity')
    CommercialOpportunityFollowUp = apps.get_model('checklists', 'CommercialOpportunityFollowUp')

    for opportunity in CommercialOpportunity.objects.all():
        scheduled_date = opportunity.created_at.date() if opportunity.created_at else timezone.localdate()
        opportunity.next_follow_up_date = scheduled_date
        opportunity.save(update_fields=['next_follow_up_date'])
        CommercialOpportunityFollowUp.objects.create(
            opportunity=opportunity,
            previous_date=None,
            scheduled_date=scheduled_date,
            note='Data inicial criada durante a migração do histórico de follow-up.',
            actor=None,
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('checklists', '0020_rework_funnel_model_standard_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='commercialopportunity',
            name='next_follow_up_date',
            field=models.DateField(blank=True, null=True, verbose_name='Data próx. Follow-Up'),
        ),
        migrations.CreateModel(
            name='CommercialOpportunityFollowUp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('previous_date', models.DateField(blank=True, null=True, verbose_name='Data anterior')),
                ('scheduled_date', models.DateField(verbose_name='Nova data de follow-up')),
                ('note', models.TextField(blank=True, verbose_name='Observação')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Registrado em')),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='commercial_follow_up_events', to=settings.AUTH_USER_MODEL, verbose_name='Usuário')),
                ('opportunity', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='follow_up_events', to='checklists.commercialopportunity', verbose_name='Oportunidade')),
            ],
            options={
                'verbose_name': 'Histórico de follow-up comercial',
                'verbose_name_plural': 'Históricos de follow-up comercial',
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.RunPython(initialize_follow_up_dates, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='commercialopportunity',
            name='next_follow_up_date',
            field=models.DateField(verbose_name='Data próx. Follow-Up'),
        ),
    ]
