# AGENTS.md - Checklist

## Contexto do projeto

Checklist é um sistema web interno da My Robot Barra da Tijuca para controle de rotinas operacionais.

O sistema é de uso interno e não deve ser exposto diretamente à internet. Ele deve permanecer simples, auditável e seguro.

A aplicação controla rotinas por tipo de usuário comum/cargo. Usuários administradores gerenciam configurações, usuários, atividades, indicadores e metas. Usuários comuns executam atividades e registram evidências.

## Stack

- Python 3.12
- Django
- PostgreSQL
- Docker Compose
- Gunicorn
- WhiteNoise

## Comandos padrão

Antes de alterar código, verificar o estado do Git:

```powershell
git status
```

Comandos principais de validação e operação local:

```powershell
docker compose up -d --build
docker compose logs --tail=120 web
docker compose exec web python manage.py makemigrations --check --dry-run
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_operational_data
```

## Regras de desenvolvimento

- Nunca commitar `.env`.
- Nunca commitar `media/`, `logs/`, `backups/` ou `staticfiles/`.
- Toda alteração em `models.py` deve ter migration correspondente.
- Não remover migrations existentes.
- Evitar alterações grandes demais em um único commit.
- Preferir CRUDs com inativação lógica em vez de exclusão física.
- Não armazenar senhas em logs.
- Não expor evidências publicamente.
- Antes de finalizar, validar Docker, migrations e seed.

## Padrão de resposta esperado

Ao finalizar uma tarefa, responder com:

- Arquivos alterados.
- Motivo técnico.
- Comandos executados.
- Resultado dos testes.
- Pendências.
- Instruções para testar.
