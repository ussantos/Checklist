import re
from django.core.exceptions import ValidationError


class StrongPasswordValidator:
    """Validador simples para senha forte.

    Regras internas adotadas para usuários da aplicação:
    - pelo menos 12 caracteres;
    - pelo menos uma letra maiúscula;
    - pelo menos uma letra minúscula;
    - pelo menos um número;
    - pelo menos um caractere especial.
    """

    def validate(self, password, user=None):
        errors = []
        if len(password or '') < 12:
            errors.append('ter pelo menos 12 caracteres')
        if not re.search(r'[A-Z]', password or ''):
            errors.append('conter pelo menos uma letra maiúscula')
        if not re.search(r'[a-z]', password or ''):
            errors.append('conter pelo menos uma letra minúscula')
        if not re.search(r'\d', password or ''):
            errors.append('conter pelo menos um número')
        if not re.search(r'[^A-Za-z0-9]', password or ''):
            errors.append('conter pelo menos um caractere especial')
        if errors:
            raise ValidationError('A senha deve ' + ', '.join(errors) + '.', code='password_not_strong')

    def get_help_text(self):
        return 'A senha deve ter pelo menos 12 caracteres, letra maiúscula, letra minúscula, número e caractere especial.'
