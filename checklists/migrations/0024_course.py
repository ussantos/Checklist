# Generated manually for Checklist on 2026-06-29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0023_commercial_stage_history'),
    ]

    operations = [
        migrations.CreateModel(
            name='Course',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=160, unique=True, verbose_name='Nome')),
                ('value', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='Valor')),
                ('active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
            ],
            options={
                'verbose_name': 'Curso',
                'verbose_name_plural': 'Cursos',
                'ordering': ['name'],
            },
        ),
    ]
