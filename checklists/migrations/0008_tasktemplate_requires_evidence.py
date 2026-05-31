from django.db import migrations, models


def set_requires_evidence_from_text(apps, schema_editor):
    TaskTemplate = apps.get_model('checklists', 'TaskTemplate')
    TaskTemplate.objects.filter(evidence_required='').update(requires_evidence=False)


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0007_tasktemplate_expected_result_tasktemplate_notes_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tasktemplate',
            name='requires_evidence',
            field=models.BooleanField(
                default=True,
                help_text='Quando marcado, o usuário comum deve registrar evidência ao concluir a atividade.',
                verbose_name='Exige evidência',
            ),
        ),
        migrations.RunPython(set_requires_evidence_from_text, migrations.RunPython.noop),
    ]
