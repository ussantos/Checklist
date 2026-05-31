# Checklist — My Robot Barra da Tijuca

[For English click here](#english-us)

Sistema web interno para controle de checklist operacionais da My Robot Barra da Tijuca.

A aplicação controla a rotina por **cargo**, mas o acesso é feito por **usuário nominal**. Isso evita uso de login genérico e preserva evidência trabalhista/operacional: cada lançamento fica associado ao usuário logado e ao cargo exercido.

## Licença e disclaimer de uso

Esta aplicação é distribuída sob a licença <a href="https://www.gnu.org/licenses/gpl-3.0.html" target="_blank" rel="noopener noreferrer">GNU GPL v3</a>.

O sistema nasceu de uma necessidade interna da unidade My Robot Barra da Tijuca para acompanhar, documentar e organizar as atividades diárias, semanais e mensais dos colaboradores da unidade.

Este projeto é destinado a **uso interno**, em ambiente controlado, preferencialmente em rede local, VPN ou servidor não exposto publicamente. **Nunca publique esta aplicação diretamente na internet sem uma revisão técnica completa de segurança, infraestrutura, privacidade e conformidade legal.**

Este sistema **não é um produto comercial** vendido, licenciado ou garantido pela My Robot Barra da Tijuca, por seus responsáveis ou por seus colaboradores. O código é disponibilizado sem garantia de funcionamento, adequação jurídica, trabalhista, fiscal, contábil, técnica, segurança ou continuidade.

Qualquer uso por outras empresas, franquias, unidades, organizações ou terceiros ocorre **por conta e risco próprios**. Antes de usar, adaptar ou implantar este sistema, cada organização deve validar a aplicação com seus responsáveis técnicos, jurídicos, contábeis, trabalhistas e de proteção de dados.

Como o sistema pode armazenar evidências contendo dados de colaboradores, alunos, responsáveis, imagens, documentos e informações operacionais, seu uso deve observar boas práticas de segurança da informação, controle de acesso, backup, retenção e privacidade, inclusive LGPD quando aplicável.

## Documentação complementar

- [Checklist de Teste de Produção](docs/TESTE_PRODUCAO.md)
- [Operação Anual e Retenção por 5 anos](docs/OPERACAO_ANUAL.md)

Use o checklist de produção antes de liberar o sistema oficialmente. Use o guia anual para congelar a instância de cada ano, validar backup/restauração e iniciar o ano seguinte.

## Perfis e cargos

O sistema trabalha com dois perfis lógicos:

- **Administrador**: acompanha todos os cargos, cadastra usuários, redefine senhas, configura atividades/indicadores/metas e acessa relatórios gerais.
- **Usuário comum/operacional**: executa atividades, registra evidências quando exigidas e acompanha apenas seus próprios indicadores e metas.

Os tipos/cargos de usuários comuns são configuráveis, por exemplo **Atendente Comercial**, **Instrutor de Cursos Livres** ou outros cargos futuros. Cargos, usuários, atividades e indicadores não devem ser excluídos fisicamente pela interface; quando deixam de valer, são inativados para preservar histórico.

## Funcionamento de usuários

- O primeiro usuário da aplicação é o administrador técnico `checklistadmin`.
- O `checklistadmin` é criado automaticamente pelo seed inicial.
- A partir dele, devem ser cadastrados usuários nominais com função de **Administrador** ou vinculados a um tipo/cargo operacional ativo.
- Não há usuários operacionais genéricos para execução diária.
- No cadastro, o administrador informa nome completo, usuário de login, e-mail opcional e função/perfil. A senha forte é gerada automaticamente pelo sistema e exibida uma única vez.
- Ao redefinir senha de um usuário, o sistema também gera uma nova senha temporária e exibe uma única vez ao administrador.
- A obrigatoriedade de trocar a senha no primeiro login é controlada por `FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN` no `.env`.
- A tela **Trocar senha** funciona para qualquer tipo de usuário: administrador, atendente ou instrutor.

## Regras de senha forte

A senha deve ter pelo menos 12 caracteres, uma letra maiúscula, uma letra minúscula, um número e um caractere especial.

Senhas criadas ou redefinidas por administradores seguem essa regra automaticamente. Elas não são enviadas por e-mail, não aparecem em logs e não podem ser exibidas novamente após a tela de confirmação.

## Recursos principais

- Login local.
- Cadastro nominal de usuários por administradores.
- Criação de usuários com função de Administrador ou cargo operacional.
- Geração automática de senha temporária forte para novos usuários e redefinições.
- Checklist por cargo com visões de dia, semana e mês para usuários comuns.
- Sugestão de novas atividades ou desativação de atividades por usuários comuns, com aprovação administrativa.
- CRUD administrativo de tipos/cargos, atividades e indicadores, sempre com inativação lógica.
- Dashboard interno de indicadores e metas por período.
- Histórico filtrável.
- Auditoria administrativa com antes/depois e exportação CSV.
- Exportação CSV.
- Evidência textual por atividade.
- Upload de múltiplos arquivos por atividade.
- Suporte a PDF, imagens, prints e fotos.
- Identificação automática do usuário logado em cada lançamento.
- Anexos protegidos por login e permissão no cargo.
- Painel administrativo Django para manutenção avançada.
- Backup diário às 20h com dump PostgreSQL, arquivos de evidência e configurações.
- Script de restauração.

## Status das atividades operacionais

- Pendente
- Executando
- Atrasada
- Concluída

Ao marcar uma atividade como **Concluída**, o sistema exige evidência textual ou pelo menos um arquivo anexado quando a atividade estiver configurada para exigir evidência. Para **Atrasada**, o sistema exige observação operacional.

## Evidências aceitas

Extensões aceitas por padrão: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` e `.heic`.

O limite efetivo para evidências operacionais é de até 5 MB por arquivo.

## Arquitetura

- Python 3.12
- Django
- PostgreSQL
- Gunicorn
- WhiteNoise para arquivos estáticos
- Docker Compose
- Grafana para dashboards internos
- Backup via `pg_dump` + `rclone`

## Estrutura simplificada

```text
.
├── checklists/                 # App principal Django
├── docs/                       # Documentação operacional e testes
├── grafana/                    # Provisionamento de datasource Grafana
├── myrobot_checklist/          # Configuração do projeto Django
├── seed/                       # CSVs com tarefas iniciais por cargo
├── scripts/                    # entrypoint, backup e restore
├── static/                     # CSS
├── templates/                  # Telas HTML
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Instalação no Ubuntu 24.04 LTS

Instale o Docker, clone este repositório em `/opt/checklist`, crie o arquivo `.env` com base no `.env.example`, ajuste as variáveis de ambiente e suba a aplicação.

Variável obrigatória para o administrador inicial:

```env
INITIAL_CHECKLISTADMIN_PASSWORD=Trocar@Senha2026
```

Para controlar a troca obrigatória no primeiro login de usuários criados ou redefinidos por administradores:

```env
FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN=False
```

Use `True` quando quiser obrigar esses usuários a trocar a senha temporária antes de acessar o restante do sistema.

Depois de subir o sistema, acesse com:

```text
Usuário: checklistadmin
Senha: valor definido em INITIAL_CHECKLISTADMIN_PASSWORD
```

Após o primeiro acesso, troque a senha do `checklistadmin` e crie os administradores nominais necessários.

Subir a aplicação:

```bash
cd /opt/checklist
docker compose up -d --build
```

Por padrão, o container não recria automaticamente as atividades e indicadores operacionais. Para carregar a base operacional padrão, defina `AUTO_SEED_OPERATIONAL_DATA=True` no `.env` ou rode manualmente:

```bash
docker compose exec web python manage.py seed_operational_data
```

Ver logs:

```bash
docker compose logs -f web
```

Acesse pelo endereço configurado no servidor, por exemplo:

```text
http://IP_DO_SERVIDOR:8000
```

## Grafana interno

O Docker Compose também sobe um Grafana para validação e criação futura de dashboards. Ele é publicado por padrão apenas em `127.0.0.1:3000`, ou seja, acessível localmente na máquina/servidor onde o Compose está rodando.

Variáveis no `.env`:

```env
GRAFANA_BIND=127.0.0.1:3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=troque-esta-senha-grafana
```

Acesse localmente:

```text
http://127.0.0.1:3000
```

O datasource PostgreSQL é provisionado automaticamente com o nome `Checklist PostgreSQL`, usando o banco da aplicação (`db:5432`). Nenhum dashboard é provisionado por padrão.

Estratégia de permissão: o Grafana não herda as permissões do Django. Por isso, nesta fase ele deve ser tratado como ferramenta administrativa, acessível apenas localmente, por VPN ou rede interna restrita. Usuários comuns devem acompanhar seus próprios indicadores pelo dashboard interno do Checklist, que aplica as permissões do sistema e impede acesso a outros cargos/usuários.

Para logs:

```bash
docker compose logs -f grafana
```

Mantenha `GRAFANA_BIND=127.0.0.1:3000` para uso local. Para acesso por rede interna/VPN, ajuste o bind conscientemente e proteja com firewall.

Antes de liberar uso oficial, execute os testes em `docs/TESTE_PRODUCAO.md`.

## Uso operacional

### Administradores

Usuários administradores podem cadastrar outros administradores, cadastrar usuários operacionais, definir cargos, configurar atividades e indicadores/metas, aprovar sugestões de atividades, redefinir senha, visualizar dashboards, filtrar histórico, exportar CSV, consultar auditoria administrativa, revisar evidências e acessar o painel `/admin/`.

### Usuários operacionais

Usuários operacionais acessam o sistema com usuário individual. O sistema mostra apenas atividades, indicadores e metas de acordo com o cargo cadastrado, grava automaticamente o nome do usuário logado no histórico e permite sugerir novas atividades ou desativação de atividades existentes.

## Backup diário às 20h

A tela administrativa **Backups** permite configurar backup local, envio opcional para Google Drive ou OneDrive via `rclone` e restauração de backups locais. A aplicação não armazena credenciais OAuth: configure a autenticação do `rclone` no container com `docker compose exec web rclone config`.

No `rclone`, cada **remoto** é uma conta configurada. Se você criar o remoto `gdrive` autenticado com uma conta Google e o remoto `onedrive` autenticado com uma conta Microsoft, a tela Backups usará a conta do remoto selecionado. Na tela, informe o remoto e a pasta, por exemplo remoto `gdrive` e pasta `MyRobotBackups/checklist`, que formam o destino `gdrive:MyRobotBackups/checklist`.

O script `scripts/backup.sh` executa o comando Django `run_configured_backup`, gerando dump PostgreSQL, pasta `media/`, `.env`, configurações, seeds e scripts. Os diretórios `backups/` e `rclone/` ficam montados no container `web` e devem continuar ignorados pelo Git.

Para restaurar, acesse **Backups**, baixe o backup da nuvem para a lista local se necessário, digite `RESTAURAR` na linha do backup local e confirme. Antes de substituir o banco, o sistema gera automaticamente um backup local de segurança do estado atual.

Agendamento sugerido no cron:

```cron
0 20 * * * cd /opt/checklist && /bin/bash scripts/backup.sh >> logs/backup.log 2>&1
```

## Restauração

Exemplo:

```bash
cd /opt/checklist
./scripts/restore.sh /caminho/do/backup/2026-12-31_200000
```

Antes de considerar o backup confiável, faça teste de restauração conforme `docs/TESTE_PRODUCAO.md`.

## Encerramento anual da instância

Para congelar o ano, validar backup/restauração e iniciar uma nova instância, siga `docs/OPERACAO_ANUAL.md`.

Recomendação para controle anual:

```text
/opt/checklist/2026
/opt/checklist/2027
/opt/checklist/2028
```

Mantenha os backups anuais por pelo menos 5 anos em dois locais: servidor/local e nuvem.

## Configuração recomendada do computador/servidor

Para poucos usuários, checklists diários, evidências em PDF/imagem e retenção de 1 ano ativo + 5 anos arquivados:

| Cenário | Configuração |
|---|---|
| Mínimo funcional | 2 cores, 4 GB RAM, SSD 256 GB |
| Recomendado | 4 cores, 8 GB RAM, SSD/NVMe 512 GB |
| Ideal com folga | 4 cores ou mais, 16 GB RAM, SSD/NVMe 1 TB |

O banco de dados deve crescer pouco. O consumo real virá principalmente dos anexos de evidência.

## Segurança operacional

- Não compartilhar usuário.
- Não expor diretamente à internet.
- Usar firewall, VPN ou rede interna.
- Trocar senhas iniciais.
- Fazer teste de restauração trimestral.
- Não guardar senhas em planilhas.
- Se houver dados de alunos, responsáveis ou crianças em evidências, tratar como informação sensível operacionalmente e restringir acesso.

<a id="english-us"></a>

## English (US)

# Checklist - My Robot Barra da Tijuca

Internal web system for managing operational checklists at My Robot Barra da Tijuca.

The application manages routines by **position**, but access is performed through **named user accounts**. This avoids generic shared logins and preserves labor/operational evidence: each entry is associated with the logged-in user and the position they perform.

## License and Usage Disclaimer

This application is distributed under the <a href="https://www.gnu.org/licenses/gpl-3.0.html" target="_blank" rel="noopener noreferrer">GNU GPL v3</a> license.

The system was created from an internal need at the My Robot Barra da Tijuca unit to track, document, and organize the daily, weekly, and monthly activities of the unit's team members.

This project is intended for **internal use** in a controlled environment, preferably on a local network, VPN, or a server that is not publicly exposed. **Never publish this application directly on the internet without a complete technical review of security, infrastructure, privacy, and legal compliance.**

This system **is not a commercial product** sold, licensed, or guaranteed by My Robot Barra da Tijuca, its owners, or its team members. The code is provided without any warranty of operation, legal fitness, labor compliance, tax/accounting adequacy, technical reliability, security, or continuity.

Any use by other companies, franchises, units, organizations, or third parties is done **at their own risk**. Before using, adapting, or deploying this system, each organization must validate it with its technical, legal, accounting, labor, and data-protection stakeholders.

Because the system may store evidence containing information about employees, students, guardians, images, documents, and operational data, its use must follow good information-security practices, access control, backup, retention, and privacy rules, including LGPD where applicable.

## Additional Documentation

- [Production Test Checklist](docs/TESTE_PRODUCAO.md)
- [Annual Operation and 5-Year Retention](docs/OPERACAO_ANUAL.md)

Use the production checklist before officially releasing the system. Use the annual guide to freeze each year's instance, validate backup/restore, and start the following year.

## Profiles and Positions

The system works with two logical profiles:

- **Administrator**: monitors all positions, creates users, resets passwords, configures activities/indicators/goals, and accesses general reports.
- **Common/operational user**: executes activities, records evidence when required, and sees only their own indicators and goals.

Common-user types/positions are configurable, for example **Commercial Attendant**, **Free Course Instructor**, or future operational positions. Positions, users, activities, and indicators must not be physically deleted through the interface; when they are no longer valid, they are deactivated to preserve history.

## User Behavior

- The first application user is the technical administrator `checklistadmin`.
- `checklistadmin` is created automatically by the initial seed.
- From that user, named users must be created either as **Administrators** or linked to an active operational position.
- There are no generic operational users for daily execution.
- During user creation, the administrator provides full name, login username, optional email, and role/profile. A strong password is generated automatically by the system and displayed only once.
- When an administrator resets a user's password, the system also generates a new temporary password and displays it only once.
- Mandatory password change on first login is controlled by `FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN` in `.env`.
- The **Change password** screen works for every user type: administrator, attendant, or instructor.

## Strong Password Rules

Passwords must have at least 12 characters, one uppercase letter, one lowercase letter, one number, and one special character.

Passwords created or reset by administrators follow this rule automatically. They are not sent by email, do not appear in logs, and cannot be displayed again after the confirmation screen.

## Main Features

- Local login.
- Named user registration by administrators.
- User creation as Administrator or operational position.
- Automatic strong temporary password generation for new users and password resets.
- Position-based checklist with day, week, and month views for common users.
- Common users can suggest new activities or activity deactivation, subject to administrator approval.
- Administrative CRUD for user types/positions, activities, and indicators, always using logical deactivation.
- Internal indicators and goals dashboard by period.
- Filterable history.
- Administrative audit trail with before/after values and CSV export.
- CSV export.
- Textual evidence per activity.
- Multiple file uploads per activity.
- Support for PDFs, images, screenshots, and photos.
- Automatic identification of the logged-in user for each entry.
- Attachments protected by login and position permission.
- Django admin panel for advanced maintenance.
- Daily backup at 8 PM with PostgreSQL dump, evidence files, and configuration files.
- Restore script.

## Operational Activity Statuses

- Pending
- In progress
- Late
- Completed

When an activity is marked as **Completed**, the system requires textual evidence or at least one attached file if the activity is configured to require evidence. For **Late**, the system requires an operational note.

## Accepted Evidence

Accepted extensions by default: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, and `.heic`.

The effective limit for operational evidence is up to 5 MB per file.

## Architecture

- Python 3.12
- Django
- PostgreSQL
- Gunicorn
- WhiteNoise for static files
- Docker Compose
- Grafana for internal dashboards
- Backup via `pg_dump` + `rclone`

## Simplified Structure

```text
.
├── checklists/                 # Main Django app
├── docs/                       # Operational and testing documentation
├── grafana/                    # Grafana datasource provisioning
├── myrobot_checklist/          # Django project configuration
├── seed/                       # CSVs with initial position-based tasks
├── scripts/                    # entrypoint, backup, and restore
├── static/                     # CSS
├── templates/                  # HTML screens
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## Installation on Ubuntu 24.04 LTS

Install Docker, clone this repository into `/opt/checklist`, create `.env` based on `.env.example`, adjust the environment variables, and start the application.

Required variable for the initial administrator:

```env
INITIAL_CHECKLISTADMIN_PASSWORD=Trocar@Senha2026
```

To control mandatory password change on first login for users created or reset by administrators:

```env
FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN=False
```

Use `True` when you want to force these users to change their temporary password before accessing the rest of the system.

After starting the system, log in with:

```text
Username: checklistadmin
Password: value defined in INITIAL_CHECKLISTADMIN_PASSWORD
```

After the first login, change the `checklistadmin` password and create the required named administrators.

Start the application:

```bash
cd /opt/checklist
docker compose up -d --build
```

By default, the container does not automatically recreate operational activities and indicators. To load the default operational dataset, set `AUTO_SEED_OPERATIONAL_DATA=True` in `.env` or run it manually:

```bash
docker compose exec web python manage.py seed_operational_data
```

View logs:

```bash
docker compose logs -f web
```

Access the configured server address, for example:

```text
http://SERVER_IP:8000
```

## Internal Grafana

Docker Compose also starts Grafana for validation and future dashboard work. By default it is published only on `127.0.0.1:3000`, meaning it is accessible locally on the machine/server running Compose.

Variables in `.env`:

```env
GRAFANA_BIND=127.0.0.1:3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=troque-esta-senha-grafana
```

Access locally:

```text
http://127.0.0.1:3000
```

The PostgreSQL datasource is provisioned automatically with the name `Checklist PostgreSQL`, using the application database (`db:5432`). No dashboards are provisioned by default.

Permission strategy: Grafana does not inherit Django permissions. Therefore, at this stage it must be treated as an administrative tool, accessible only locally, through VPN, or via a restricted internal network. Common users must track their own indicators through the internal Checklist dashboard, which applies application permissions and prevents access to other positions/users.

For logs:

```bash
docker compose logs -f grafana
```

Keep `GRAFANA_BIND=127.0.0.1:3000` for local use. For internal-network/VPN access, change the bind deliberately and protect it with a firewall.

Before official release, run the tests in `docs/TESTE_PRODUCAO.md`.

## Operational Use

### Administrators

Administrators can create other administrators, create operational users, define positions, configure activities and indicators/goals, approve activity suggestions, reset passwords, view dashboards, filter history, export CSV files, consult the administrative audit trail, review evidence, and access the `/admin/` panel.

### Operational Users

Operational users access the system with individual user accounts. The system shows only activities, indicators, and goals according to the user's registered position, automatically records the logged-in user's name in history, and allows users to suggest new activities or deactivation of existing activities.

## Daily Backup at 8 PM

The admin **Backups** screen lets administrators configure local backup, optional upload to Google Drive or OneDrive through `rclone`, and local backup restore. The application does not store OAuth credentials: configure `rclone` authentication in the container with `docker compose exec web rclone config`.

In `rclone`, each **remote** is a configured account. If you create a `gdrive` remote authenticated with one Google account and an `onedrive` remote authenticated with one Microsoft account, the Backups screen will use the account behind the selected remote. In the screen, enter the remote and folder, for example remote `gdrive` and folder `MyRobotBackups/checklist`, which form the destination `gdrive:MyRobotBackups/checklist`.

The `scripts/backup.sh` script runs the Django `run_configured_backup` command, backing up the PostgreSQL database, the `media/` folder, `.env`, settings, seeds, and scripts. The `backups/` and `rclone/` directories are mounted into the `web` container and must remain ignored by Git.

To restore, open **Backups**, download the cloud backup into the local list if needed, type `RESTAURAR` on the local backup row, and confirm. Before replacing the database, the system automatically creates a local safety backup of the current state.

Suggested cron schedule:

```cron
0 20 * * * cd /opt/checklist && /bin/bash scripts/backup.sh >> logs/backup.log 2>&1
```

## Restore

Example:

```bash
cd /opt/checklist
./scripts/restore.sh /path/to/backup/2026-12-31_200000
```

Before trusting a backup, perform a restore test according to `docs/TESTE_PRODUCAO.md`.

## Annual Instance Closeout

To freeze the year, validate backup/restore, and start a new instance, follow `docs/OPERACAO_ANUAL.md`.

Recommended annual control:

```text
/opt/checklist/2026
/opt/checklist/2027
/opt/checklist/2028
```

Keep annual backups for at least 5 years in two locations: server/local and cloud.

## Recommended Computer/Server Configuration

For a small number of users, daily checklists, PDF/image evidence, and retention of 1 active year + 5 archived years:

| Scenario | Configuration |
|---|---|
| Functional minimum | 2 cores, 4 GB RAM, 256 GB SSD |
| Recommended | 4 cores, 8 GB RAM, 512 GB SSD/NVMe |
| Comfortable headroom | 4+ cores, 16 GB RAM, 1 TB SSD/NVMe |

The database should grow slowly. Actual storage usage will mainly come from evidence attachments.

## Operational Security

- Do not share user accounts.
- Do not expose directly to the internet.
- Use firewall, VPN, or an internal network.
- Change initial passwords.
- Perform quarterly restore tests.
- Do not store passwords in spreadsheets.
- If evidence includes data from students, guardians, or children, treat it as sensitive operational information and restrict access.

