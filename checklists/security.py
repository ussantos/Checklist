import secrets
import string


def generate_temporary_password(length=16):
    """Gera uma senha temporária forte para criação/redefinição de usuário.

    A senha contém, no mínimo, uma letra maiúscula, uma letra minúscula,
    um número e um caractere especial. O restante é completado com caracteres
    aleatórios do conjunto permitido.
    """
    if length < 12:
        length = 12

    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    symbols = "!@#$%&*_-+=?"
    all_chars = uppercase + lowercase + digits + symbols

    chars = [
        secrets.choice(uppercase),
        secrets.choice(lowercase),
        secrets.choice(digits),
        secrets.choice(symbols),
    ]
    chars.extend(secrets.choice(all_chars) for _ in range(length - len(chars)))
    secrets.SystemRandom().shuffle(chars)
    return ''.join(chars)
