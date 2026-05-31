from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0002_fullname_and_evidence_attachments'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='display_name',
            field=models.CharField(max_length=120, verbose_name='Nome completo'),
        ),
        migrations.AlterField(
            model_name='checklistoccurrence',
            name='executor_full_name',
            field=models.CharField(blank=True, help_text='Preenchido automaticamente a partir do cadastro do usuário que atualizou a atividade.', max_length=180, verbose_name='Nome completo do funcionário'),
        ),
    ]
