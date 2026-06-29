from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0033_lessonfeedback_module_and_lesson_number'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='checklistoccurrence',
            name='evidence_file',
        ),
        migrations.RemoveField(
            model_name='metricrecord',
            name='evidence_file',
        ),
        migrations.DeleteModel(
            name='EvidenceAttachment',
        ),
    ]
