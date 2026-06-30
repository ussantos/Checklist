from django.db import migrations, models


def mark_known_non_modular_courses(apps, schema_editor):
    Course = apps.get_model('checklists', 'Course')
    Course.objects.filter(name__iexact='My Robot Play').update(requires_module_count=False)
    Course.objects.filter(name__iexact='Colônia de Férias').update(requires_module_count=False)
    Course.objects.filter(name__iexact='Colonia de Ferias').update(requires_module_count=False)


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0043_commercialopportunity_contracted_modules'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='requires_module_count',
            field=models.BooleanField(default=True, verbose_name='Controla módulos/apostilas'),
        ),
        migrations.RunPython(mark_known_non_modular_courses, migrations.RunPython.noop),
    ]
