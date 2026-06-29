# Generated manually for Checklist on 2026-06-29

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('checklists', '0024_course'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='description',
            field=models.TextField(blank=True, default='', verbose_name='Descrição'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='course',
            name='kit_quantity',
            field=models.PositiveIntegerField(default=1, verbose_name='Quantidade de kits'),
        ),
        migrations.AddField(
            model_name='course',
            name='max_students_per_slot',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Máximo de alunos por horário'),
        ),
        migrations.CreateModel(
            name='Room',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, unique=True, verbose_name='Nome')),
                ('capacity', models.PositiveIntegerField(default=1, verbose_name='Capacidade')),
                ('active', models.BooleanField(default=True, verbose_name='Ativa')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizada em')),
            ],
            options={
                'verbose_name': 'Sala',
                'verbose_name_plural': 'Salas',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='SchoolHoliday',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField(verbose_name='Data inicial')),
                ('end_date', models.DateField(verbose_name='Data final')),
                ('kind', models.CharField(choices=[('national_holiday', 'Feriado nacional'), ('institutional_holiday', 'Feriado institucional'), ('recess', 'Recesso')], default='institutional_holiday', max_length=30, verbose_name='Tipo')),
                ('description', models.CharField(max_length=180, verbose_name='Descrição')),
                ('active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
            ],
            options={
                'verbose_name': 'Feriado/Recesso',
                'verbose_name_plural': 'Feriados/Recessos',
                'ordering': ['start_date', 'description'],
            },
        ),
        migrations.CreateModel(
            name='PedagogicalStudent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=160, verbose_name='Nome')),
                ('enrollment_number', models.CharField(blank=True, max_length=80, verbose_name='Matrícula')),
                ('responsible_name', models.CharField(blank=True, max_length=160, verbose_name='Responsável')),
                ('whatsapp', models.CharField(blank=True, max_length=30, verbose_name='WhatsApp')),
                ('status', models.CharField(choices=[('active', 'Ativo'), ('inactive', 'Desativado')], default='active', max_length=20, verbose_name='Status')),
                ('source', models.CharField(blank=True, max_length=80, verbose_name='Origem')),
                ('external_id', models.CharField(blank=True, max_length=120, verbose_name='ID externo')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
            ],
            options={
                'verbose_name': 'Aluno pedagógico',
                'verbose_name_plural': 'Alunos pedagógicos',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='TimeSlot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weekday', models.IntegerField(choices=[(0, 'Segunda-feira'), (1, 'Terça-feira'), (2, 'Quarta-feira'), (3, 'Quinta-feira'), (4, 'Sexta-feira'), (5, 'Sábado')], verbose_name='Dia da semana')),
                ('start_time', models.TimeField(verbose_name='Início')),
                ('end_time', models.TimeField(verbose_name='Fim')),
                ('active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
            ],
            options={
                'verbose_name': 'Horário pedagógico',
                'verbose_name_plural': 'Horários pedagógicos',
                'ordering': ['weekday', 'start_time', 'end_time'],
            },
        ),
        migrations.CreateModel(
            name='Lesson',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('student_name_snapshot', models.CharField(blank=True, max_length=160, verbose_name='Nome do aluno/interessado')),
                ('responsible_name_snapshot', models.CharField(blank=True, max_length=160, verbose_name='Responsável')),
                ('whatsapp_snapshot', models.CharField(blank=True, max_length=30, verbose_name='WhatsApp')),
                ('lesson_type', models.CharField(choices=[('regular', 'Matriculado'), ('trial', 'Experimental')], default='regular', max_length=20, verbose_name='Tipo')),
                ('date', models.DateField(verbose_name='Data')),
                ('start_time', models.TimeField(verbose_name='Início')),
                ('end_time', models.TimeField(verbose_name='Fim')),
                ('status', models.CharField(choices=[('scheduled', 'Agendada'), ('done', 'Realizada'), ('cancelled', 'Cancelada'), ('absent', 'Falta'), ('rescheduled', 'Reagendada')], default='scheduled', max_length=20, verbose_name='Status')),
                ('notes', models.TextField(blank=True, verbose_name='Observação')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lessons', to='checklists.course', verbose_name='Curso')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pedagogical_lessons_created', to=settings.AUTH_USER_MODEL, verbose_name='Criado por')),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lessons', to='checklists.room', verbose_name='Sala')),
                ('student', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='lessons', to='checklists.pedagogicalstudent', verbose_name='Aluno')),
            ],
            options={
                'verbose_name': 'Aula',
                'verbose_name_plural': 'Aulas',
                'ordering': ['date', 'start_time', 'room__name', 'student_name_snapshot'],
                'indexes': [
                    models.Index(fields=['date', 'start_time', 'end_time'], name='lesson_date_time_idx'),
                    models.Index(fields=['course', 'date', 'start_time'], name='lesson_course_date_idx'),
                    models.Index(fields=['room', 'date', 'start_time'], name='lesson_room_date_idx'),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name='pedagogicalstudent',
            constraint=models.UniqueConstraint(condition=~models.Q(enrollment_number=''), fields=('enrollment_number',), name='unique_pedagogical_student_enrollment'),
        ),
        migrations.AddConstraint(
            model_name='timeslot',
            constraint=models.UniqueConstraint(fields=('weekday', 'start_time', 'end_time'), name='unique_pedagogical_timeslot'),
        ),
    ]
