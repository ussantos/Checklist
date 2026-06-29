# Generated manually for Checklist on 2026-06-29

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0018_commercialfunnel'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommercialOpportunity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=160, verbose_name='Oportunidade')),
                ('contact_name', models.CharField(max_length=120, verbose_name='Nome do responsável')),
                ('contact_phone', models.CharField(max_length=30, verbose_name='Telefone do responsável')),
                ('field_values', models.JSONField(blank=True, default=dict, verbose_name='Campos adicionais preenchidos')),
                ('notes', models.TextField(blank=True, verbose_name='Observações')),
                ('active', models.BooleanField(default=True, verbose_name='Ativa')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizada em')),
                ('commercial_funnel', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='opportunities', to='checklists.commercialfunnel', verbose_name='Funil')),
            ],
            options={
                'verbose_name': 'Oportunidade comercial',
                'verbose_name_plural': 'Oportunidades comerciais',
                'ordering': [
                    'commercial_funnel__funnel_model__funnel_type__name',
                    'commercial_funnel__funnel_model__stage__order',
                    'commercial_funnel__funnel_model__stage__name',
                    'title',
                ],
            },
        ),
    ]
