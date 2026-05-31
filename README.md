# Checkups — My Robot Barra da Tijuca

Sistema web interno para controle de checkups/checklists operacionais da My Robot Barra da Tijuca.

A aplicação foi desenhada para controlar a rotina por **cargo**, e não por nome de funcionário. Mesmo assim, cada lançamento exige o campo **Nome completo do funcionário**, para identificar quem executou a atividade naquele dia.

## Cargos operacionais

- Atendente Comercial
- Instrutor de Aula Livre

## Recursos principais

- Login local.
- Checklist diário por cargo.
- Visão semanal.
- Dashboard mensal.
- Histórico filtrável.
- Exportação CSV.
- Upload de evidências por atividade.
- Evidência textual por atividade.
- Múltiplos anexos por atividade.
- Suporte a PDF e imagens/prints/fotos.
- Campo obrigatório de nome completo em cada lançamento.
- Painel administrativo Django.
- Backup diário às 20h com dump PostgreSQL, arquivos de evidência e configurações.
- Restauração por script.

## Observação sobre os arquivos

O pacote completo da aplicação foi gerado no ChatGPT como arquivo ZIP. Para publicar todos os arquivos no repositório, baixe o ZIP, extraia o conteúdo e execute:

```bash
cd /caminho/onde/extraiu/myrobot_checklist_system_funcional
git init
git remote add origin https://github.com/ussantos/checkups.git
git branch -M main
git add .
git commit -m "Add functional checklist system"
git push -u origin main
```

Se o repositório já tiver este README, use:

```bash
git pull origin main --allow-unrelated-histories
git add .
git commit -m "Add functional checklist system"
git push origin main
```

## Instalação resumida no Ubuntu 24.04 LTS

```bash
sudo mkdir -p /opt/checkups
sudo chown -R $USER:$USER /opt/checkups
cd /opt/checkups
git clone https://github.com/ussantos/checkups.git .
cp .env.example .env
nano .env
docker compose up -d --build
```

Acesso:

```text
http://IP_DO_SERVIDOR:8000
```

## Usuários iniciais

Administradores:

- `uellington`
- `liliane`

Operacionais:

- `atendente.comercial`
- `instrutor.aula.livre`

As senhas iniciais ficam no `.env` e devem ser trocadas após o primeiro acesso.

## Evidências

Cada tarefa permite registrar:

- nome completo do funcionário;
- status;
- evidência textual;
- múltiplos anexos;
- PDF;
- imagens;
- motivo de pendência ou bloqueio.

Ao concluir uma tarefa, o sistema exige evidência textual ou anexo. Para status Bloqueado/Pendente, exige justificativa.

## Backup diário

O backup está previsto para rodar às 20h por cron:

```cron
0 20 * * * cd /opt/checkups && /bin/bash scripts/backup.sh >> logs/backup.log 2>&1
```

O backup inclui:

- dump do PostgreSQL;
- pasta `media/` com evidências;
- `.env`;
- `docker-compose.yml`;
- scripts;
- seeds;
- código da aplicação.

O envio para Google Drive ou OneDrive é feito via `rclone`.
