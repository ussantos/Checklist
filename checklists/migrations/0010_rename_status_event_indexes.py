from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0009_checklistoccurrencestatusevent'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='checklistoccurrencestatusevent',
            new_name='checklists__occurre_b43806_idx',
            old_name='checklists__occur_3b542f_idx',
        ),
        migrations.RenameIndex(
            model_name='checklistoccurrencestatusevent',
            new_name='checklists__changed_0ff3b0_idx',
            old_name='checklists__changed_f98612_idx',
        ),
        migrations.RenameIndex(
            model_name='checklistoccurrencestatusevent',
            new_name='checklists__new_sta_ccdc9f_idx',
            old_name='checklists__new_sta_8b576e_idx',
        ),
    ]
