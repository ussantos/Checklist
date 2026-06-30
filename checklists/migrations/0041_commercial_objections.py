from django.db import migrations, models
import django.db.models.deletion


DEFAULT_COMMERCIAL_OBJECTIONS = [
    'Não gostou do valor / preço',
    'Questão financeira',
    'Mora longe da unidade',
    'Horário incompatível',
    'Vai pensar / vai analisar',
    'Precisa conversar com o pai/mãe ou outro responsável',
    'Desistiu',
    'Não tem interesse',
    'Fez aula experimental, mas não matriculou',
    'Não compareceu à aula experimental',
    'Aula experimental remarcada',
    'Entrou em lista de espera',
    'Encontrou outra solução (escola/concorrente)',
    'Procurava outro produto ou serviço (filamento, impressão 3D, Excel, montagem de computador etc.)',
    'Apenas curiosidade / sem intenção de compra',
    'Lead falso / trote',
    'Não responde / parou de responder (ghosting)',
]


def seed_commercial_objections(apps, schema_editor):
    CommercialObjection = apps.get_model('checklists', 'CommercialObjection')
    for name in DEFAULT_COMMERCIAL_OBJECTIONS:
        CommercialObjection.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0040_alter_pedagogicalreporttask_lesson_number'),
    ]

    operations = [
        migrations.CreateModel(
            name='CommercialObjection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=180, unique=True, verbose_name='Objeção')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criada em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizada em')),
            ],
            options={
                'verbose_name': 'Objeção comercial',
                'verbose_name_plural': 'Objeções comerciais',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='commercialopportunity',
            name='objection',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='opportunities',
                to='checklists.commercialobjection',
                verbose_name='Objeção',
            ),
        ),
        migrations.RunPython(seed_commercial_objections, migrations.RunPython.noop),
    ]
