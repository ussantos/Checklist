# Generated manually for Checklist on 2026-06-29

from django.db import migrations, models


def seed_funnel_types(apps, schema_editor):
    FunnelType = apps.get_model('checklists', 'FunnelType')
    initial_types = [
        ('interessados', 'Interessados'),
        ('qualificados', 'Qualificados'),
        ('parcerias', 'Parcerias'),
    ]
    for code, name in initial_types:
        funnel_type, _ = FunnelType.objects.get_or_create(
            code=code,
            defaults={'name': name, 'active': True},
        )
        updates = []
        if funnel_type.name != name:
            funnel_type.name = name
            updates.append('name')
        if not funnel_type.active:
            funnel_type.active = True
            updates.append('active')
        if updates:
            funnel_type.save(update_fields=updates)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0015_backup_schedule_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='FunnelType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=80, unique=True, verbose_name='Código')),
                ('name', models.CharField(max_length=120, unique=True, verbose_name='Tipo de funil')),
                ('active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
            ],
            options={
                'verbose_name': 'Tipo de funil',
                'verbose_name_plural': 'Tipos de funis',
                'ordering': ['name'],
            },
        ),
        migrations.RunPython(seed_funnel_types, noop_reverse),
    ]
