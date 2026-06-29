# Generated manually for Checklist on 2026-06-29

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0016_funneltype'),
    ]

    operations = [
        migrations.CreateModel(
            name='FunnelStage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=80, unique=True, verbose_name='Código')),
                ('name', models.CharField(max_length=120, unique=True, verbose_name='Etapa')),
                ('description', models.TextField(blank=True, verbose_name='Descrição')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Ordem')),
                ('active', models.BooleanField(default=True, verbose_name='Ativa')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizada em')),
            ],
            options={
                'verbose_name': 'Etapa de funil',
                'verbose_name_plural': 'Etapas de funis',
                'ordering': ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='OpportunityOrigin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=80, unique=True, verbose_name='Código')),
                ('name', models.CharField(max_length=120, unique=True, verbose_name='Origem')),
                ('description', models.TextField(blank=True, verbose_name='Descrição')),
                ('active', models.BooleanField(default=True, verbose_name='Ativa')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizada em')),
            ],
            options={
                'verbose_name': 'Origem de oportunidade',
                'verbose_name_plural': 'Origens de oportunidades',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='FunnelModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('responsible_name', models.CharField(max_length=120, verbose_name='Nome do responsável')),
                ('responsible_phone', models.CharField(max_length=30, verbose_name='Telefone do responsável')),
                ('active', models.BooleanField(default=True, verbose_name='Ativado')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('funnel_type', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='funnel_models', to='checklists.funneltype', verbose_name='Tipo')),
                ('origin', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='funnel_models', to='checklists.opportunityorigin', verbose_name='Origem')),
                ('stage', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='funnel_models', to='checklists.funnelstage', verbose_name='Etapa')),
            ],
            options={
                'verbose_name': 'Modelo de funil',
                'verbose_name_plural': 'Modelos de funis',
                'ordering': ['funnel_type__name', 'stage__order', 'stage__name', 'responsible_name'],
            },
        ),
        migrations.CreateModel(
            name='FunnelModelField',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, verbose_name='Nome do campo')),
                ('field_type', models.CharField(choices=[('TEXT', 'Texto'), ('DATETIME', 'Data e Hora'), ('BOOLEAN', 'Verdadeiro/Falso'), ('SELECT', 'Caixa de Seleção'), ('INTEGER', 'Número Inteiro')], max_length=20, verbose_name='Tipo do campo')),
                ('required', models.BooleanField(default=False, verbose_name='Obrigatório')),
                ('options', models.JSONField(blank=True, default=list, verbose_name='Opções')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='Ordem')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('funnel_model', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fields', to='checklists.funnelmodel')),
            ],
            options={
                'verbose_name': 'Campo de modelo de funil',
                'verbose_name_plural': 'Campos de modelos de funis',
                'ordering': ['order', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='funnelmodelfield',
            constraint=models.UniqueConstraint(fields=('funnel_model', 'name'), name='unique_field_name_per_funnel_model'),
        ),
    ]
