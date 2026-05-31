# Generated for My Robot Checklist System - evidence attachments and executor identification.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('checklists', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='checklistoccurrence',
            name='executor_full_name',
            field=models.CharField(blank=True, help_text='Nome da pessoa que executou ou atualizou esta atividade. O usuário do sistema é por cargo; este campo identifica o funcionário real.', max_length=180, verbose_name='Nome completo do funcionário'),
        ),
        migrations.AddField(
            model_name='dailynote',
            name='executor_full_name',
            field=models.CharField(blank=True, max_length=180, verbose_name='Nome completo do responsável pelo resumo'),
        ),
        migrations.AddField(
            model_name='metricrecord',
            name='executor_full_name',
            field=models.CharField(blank=True, max_length=180, verbose_name='Nome completo do funcionário'),
        ),
        migrations.CreateModel(
            name='EvidenceAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='evidencias/%Y/%m/', verbose_name='Arquivo')),
                ('original_name', models.CharField(blank=True, max_length=255, verbose_name='Nome original')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True, verbose_name='Enviado em')),
                ('occurrence', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='checklists.checklistoccurrence')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Anexo de evidência',
                'verbose_name_plural': 'Anexos de evidência',
                'ordering': ['-uploaded_at'],
            },
        ),
    ]
