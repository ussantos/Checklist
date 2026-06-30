import decimal

from django.db import migrations, models


SCORE_CHOICES = [
    (decimal.Decimal(step) / decimal.Decimal('2'), f'{decimal.Decimal(step) / decimal.Decimal("2"):g}'.replace('.', ','))
    for step in range(0, 21)
]


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0041_commercial_objections'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lessonfeedback',
            name='assembly_score',
            field=models.DecimalField(choices=SCORE_CHOICES, decimal_places=1, max_digits=3, verbose_name='Montagem nota'),
        ),
        migrations.AlterField(
            model_name='lessonfeedback',
            name='programming_score',
            field=models.DecimalField(blank=True, choices=SCORE_CHOICES, decimal_places=1, max_digits=3, null=True, verbose_name='Programação nota'),
        ),
        migrations.AlterField(
            model_name='lessonfeedback',
            name='participation_score',
            field=models.DecimalField(choices=SCORE_CHOICES, decimal_places=1, max_digits=3, verbose_name='Interesse/Participação nota'),
        ),
        migrations.AlterField(
            model_name='lessonfeedback',
            name='behavior_score',
            field=models.DecimalField(choices=SCORE_CHOICES, decimal_places=1, max_digits=3, verbose_name='Comportamento nota'),
        ),
    ]
