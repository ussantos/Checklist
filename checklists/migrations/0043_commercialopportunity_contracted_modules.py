from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0042_lessonfeedback_decimal_scores'),
    ]

    operations = [
        migrations.AddField(
            model_name='commercialopportunity',
            name='contracted_modules',
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, '1 módulo'), (2, '2 módulos'), (3, '3 módulos')],
                null=True,
                verbose_name='Módulos contratados',
            ),
        ),
    ]
