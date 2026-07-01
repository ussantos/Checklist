from django.db import migrations
from django.utils.text import slugify


def rename_matricula_stage_to_ganha(apps, schema_editor):
    FunnelStage = apps.get_model('checklists', 'FunnelStage')
    CommercialOpportunity = apps.get_model('checklists', 'CommercialOpportunity')

    stages = list(FunnelStage.objects.all().order_by('id'))
    legacy_stages = [
        stage for stage in stages
        if 'matricula' in slugify(f'{stage.code} {stage.name}') and '5' in slugify(f'{stage.code} {stage.name}')
    ]
    target = FunnelStage.objects.filter(code='5-ganha').first() or FunnelStage.objects.filter(name='5 - Ganha').first()

    if target is None:
        target = legacy_stages[0] if legacy_stages else FunnelStage()

    target.code = '5-ganha'
    target.name = '5 - Ganha'
    target.order = target.order or 5
    target.active = True
    target.save()

    for legacy in legacy_stages:
        if legacy.pk == target.pk:
            continue
        CommercialOpportunity.objects.filter(stage=legacy).update(stage=target)
        legacy.code = f'5-matricula-legado-{legacy.pk}'
        legacy.name = f'5 - Matrícula (legado {legacy.pk})'
        legacy.active = False
        legacy.save(update_fields=['code', 'name', 'active', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0044_course_requires_module_count'),
    ]

    operations = [
        migrations.RunPython(rename_matricula_stage_to_ganha, migrations.RunPython.noop),
    ]
