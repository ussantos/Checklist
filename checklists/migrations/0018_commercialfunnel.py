# Generated manually for Checklist on 2026-06-29

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0017_commercial_funnel_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommercialFunnel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=160, unique=True, verbose_name='Nome do funil')),
                ('active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('funnel_model', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='funnels', to='checklists.funnelmodel', verbose_name='Modelo de funil')),
            ],
            options={
                'verbose_name': 'Funil comercial',
                'verbose_name_plural': 'Funis comerciais',
                'ordering': ['name'],
            },
        ),
    ]
