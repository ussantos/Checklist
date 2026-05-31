from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='must_change_password',
            field=models.BooleanField(
                default=False,
                help_text='Quando marcado, o usuário é redirecionado obrigatoriamente para a troca de senha antes de usar o sistema.',
                verbose_name='Deve trocar senha no próximo login',
            ),
        ),
    ]
