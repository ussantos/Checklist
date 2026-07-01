# Checklist — My Robot Barra da Tijuca

[For English click here](#english-us)

Sistema web interno para administração operacional da My Robot Barra da Tijuca.

A aplicação controla acessos por **cargo**, mas o login é feito por **usuário nominal**. Isso evita uso de login genérico e preserva rastreabilidade administrativa.

> Estado atual: os módulos antigos de Ausências, Checklist do dia, Semana, Indicadores, Atividades e Comercial foram removidos da navegação e das rotas internas. Os dados/modelos legados podem permanecer no banco para histórico até a definição dos novos módulos.

## Licença e disclaimer de uso

Esta aplicação é distribuída sob a licença <a href="https://www.gnu.org/licenses/gpl-3.0.html" target="_blank" rel="noopener noreferrer">GNU GPL v3</a>.

O sistema nasceu de uma necessidade interna da unidade My Robot Barra da Tijuca para acompanhar, documentar e organizar as atividades diárias, semanais e mensais dos colaboradores da unidade.

Este projeto é destinado a **uso interno**, em ambiente controlado, preferencialmente em rede local, VPN ou servidor não exposto publicamente. **Nunca publique esta aplicação diretamente na internet sem uma revisão técnica completa de segurança, infraestrutura, privacidade e conformidade legal.**

Este sistema **não é um produto comercial** vendido, licenciado ou garantido pela My Robot Barra da Tijuca, por seus responsáveis ou por seus colaboradores. O código é disponibilizado sem garantia de funcionamento, adequação jurídica, trabalhista, fiscal, contábil, técnica, segurança ou continuidade.

Qualquer uso por outras empresas, franquias, unidades, organizações ou terceiros ocorre **por conta e risco próprios**. Antes de usar, adaptar ou implantar este sistema, cada organização deve validar a aplicação com seus responsáveis técnicos, jurídicos, contábeis, trabalhistas e de proteção de dados.

Como o sistema pode armazenar dados de colaboradores, alunos, responsáveis e informações operacionais, seu uso deve observar boas práticas de segurança da informação, controle de acesso, backup, retenção e privacidade, inclusive LGPD quando aplicável.

## Documentação complementar

- [Checklist de Teste de Produção](docs/TESTE_PRODUCAO.md)
- [Operação Anual e Retenção por 5 anos](docs/OPERACAO_ANUAL.md)

Use o checklist de produção antes de liberar o sistema oficialmente. Use o guia anual para congelar a instância de cada ano, validar backup/restauração e iniciar o ano seguinte.

## Perfis e cargos

O sistema trabalha com dois perfis lógicos:

- **Administrador**: cadastra usuários, redefine senhas, gerencia tipos/cargos, consulta histórico/auditoria e administra backups.
- **Usuário comum/operacional**: acessa a área operacional e troca a própria senha enquanto os novos módulos operacionais são redesenhados.

Os tipos/cargos de usuários comuns são configuráveis, por exemplo **Atendente Comercial**, **Instrutor de Cursos Livres** ou outros cargos futuros. Cargos e usuários não devem ser excluídos fisicamente pela interface; quando deixam de valer, são inativados para preservar histórico.

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
- CRUD administrativo de tipos/cargos.
- Dashboard administrativo enxuto.
- Auditoria administrativa com antes/depois e exportação CSV.
- Exportação CSV.
- Painel administrativo Django para manutenção avançada.
- Backup diário configurável com dump PostgreSQL, arquivos locais e configurações.
- Script de restauração.

Módulos removidos nesta etapa: Ausências, Checklist do dia, Semana, Histórico, Indicadores, Atividades e Comercial.

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

## Instalação no Ubuntu Server 26.04 LTS

Instale o Docker, clone este repositório em `/opt/checklist`, crie o arquivo `.env` com base no `.env.example`, ajuste as variáveis de ambiente e suba a aplicação.

Para instalar em um Ubuntu Server 26.04 LTS recém instalado usando pacote fechado, gere o instalador com:

```bash
bash scripts/build_installer_package.sh
```

Depois copie o `.tar.gz` de `dist/` para o servidor e siga `docs/INSTALACAO_UBUNTU26.md`.

O pacote instala o código, mas não carrega automaticamente os dados cadastrados no computador atual. Para instalar em outro computador mantendo cadastros, gere um backup completo em **Backups** ou com `docker compose exec web python manage.py run_configured_backup`, copie o `backup_package.tar.gz` para o novo servidor e restaure pela tela **Backups**. Em reinstalações no mesmo servidor, o instalador preserva `.env`, volume PostgreSQL, `media/`, `backups/`, `logs/`, `staticfiles/` e `rclone/`, além de tentar criar backup local antes da atualização.

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

Por padrão, o container não recria atividades e indicadores operacionais antigos. O comando abaixo mantém apenas os cargos operacionais base:

```bash
docker compose exec web python manage.py seed_operational_data
```

## Integração Sponte

A tela **Gestão Pedagógica > Alunos** possui o botão **Importar do Sponte** para buscar alunos pelo endpoint SOAP `GetAlunos`.

Configure as credenciais apenas no `.env` do servidor:

```env
SPONTE_API_ENABLED=False
SPONTE_API_BASE_URL=https://api.sponteeducacional.net.br/WSAPIEdu.asmx
SPONTE_API_CLIENT_CODE=
SPONTE_API_TOKEN=
SPONTE_API_TIMEOUT_SECONDS=30
SPONTE_API_CACHE_TTL_MINUTES=60
SPONTE_API_MAX_REQUESTS_PER_MINUTE=30
SPONTE_API_WAIT_ON_RATE_LIMIT=True
SPONTE_API_RATE_LIMIT_WAIT_PADDING_SECONDS=2
SPONTE_STUDENT_SEARCH_PARAMS=Nome=%
SPONTE_COURSE_SEARCH_PARAMS=Situacao=1
SPONTE_SCHEDULE_SYNC_DAYS_BACK=0
SPONTE_SCHEDULE_SYNC_DAYS_AHEAD=90
```

O sistema importa alunos ativos e inativos retornados pelo Sponte, incluindo nome, matrícula, responsável, WhatsApp, status, origem e ID externo. A importação cria alunos ausentes e atualiza alunos já existentes pelo par `source=Sponte`/`external_id` ou pela matrícula. O token não é gravado em logs nem no histórico. As chamadas usam cache local e limite defensivo de requisições por minuto. Quando `SPONTE_API_WAIT_ON_RATE_LIMIT=True`, sincronizações aguardam a próxima janela de minuto em vez de falhar ao alcançar o limite local.

A tela **Gestão Pedagógica > Cursos** possui o botão **Sincronizar Sponte** para buscar cursos pelo endpoint SOAP `GetCursos`. Cursos com versão `1.0` são ignorados; quando houver conflito de nome-base, a versão do Sponte, preferencialmente `2.0`, substitui o cadastro local sem exclusão física e preservando valor/kits já configurados no Checklist.

Na tela **Gestão Pedagógica > Agenda**, o botão **Sincronizar Sponte** busca a agenda de cada aluno ativo importado do Sponte pelo endpoint SOAP `GetAgendaAluno` e aproveita somente a seção **AulasLivres**. Quando o SOAP trouxer a **Situação da Aula**, o Checklist usa as mesmas nomenclaturas do Sponte: `Presença`, `Falta`, `Não dada` e `Cancelada`. Para auditorias e correções em lote, exporte o relatório Sponte **Aulas Livres** em XML com Situação da Aula = Todas e rode `reconcile_sponte_lessons --report-xml caminho.xml`; a informação do relatório prevalece sobre o banco local. Essas aulas regulares são exibidas no Checklist como somente leitura. O Checklist continua criando localmente apenas **Aulas Experimentais ou Play**. Sincronizações iniciadas pelas telas rodam em segundo plano; o usuário recebe uma notificação ao iniciar e outra ao concluir ou falhar.

Ao cadastrar uma **Aula Experimental ou Play**, o administrador deve informar se ela é `Experimental` ou `Play` e vinculá-la a uma oportunidade comercial. Uma oportunidade pode ter várias Aulas Experimentais ou Play, garantindo rastreabilidade para clientes que ainda não existem no Sponte.

Sincronizações datadas do Sponte sempre começam no dia em que a sincronização é executada e seguem para frente. `SPONTE_SCHEDULE_SYNC_DAYS_AHEAD` controla quantos dias futuros entram na agenda. `SPONTE_SCHEDULE_SYNC_DAYS_BACK` é mantida apenas por compatibilidade e deve ficar `0`. Se uma aula regular futura do Sponte não voltar mais dentro da janela sincronizada, ela é marcada como cancelada no Checklist, sem exclusão física.

Detalhes técnicos, política de cache, rate limit e cuidados LGPD estão em `docs/sponte_integration.md`.

## Feedback de Aula

A tela **Gestão Pedagógica > Feedback de Aula** substitui os antigos modelos de feedback. O Checklist usa um único formulário de feedback para aulas regulares de alunos matriculados.

O feedback é preenchido após cada aula regular sincronizada do Sponte. **Aulas Experimentais ou Play não exigem feedback** nesse fluxo. Instrutores de cursos livres e administradores podem acessar a tela.

As notas são selecionadas de 0 a 10. A pontualidade aparece como **Sim** ou **Não**, mas é registrada internamente como 10 ou 5. Quando a aula tiver programação, o instrutor marca essa opção e passa a preencher comentário e nota de programação. Se a aula não tiver programação, essa nota não entra no cálculo.

A nota geral é calculada automaticamente pela média das notas informadas e fica somente leitura no formulário.

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

Usuários administradores podem cadastrar outros administradores, cadastrar usuários operacionais, definir cargos, redefinir senha, consultar dashboard administrativo, filtrar histórico, exportar CSV, consultar auditoria administrativa, administrar backups e acessar o painel `/admin/`.

### Usuários operacionais

Usuários operacionais acessam o sistema com usuário individual e visualizam uma área operacional neutra enquanto os módulos de execução são redesenhados.

## Backup diário

A tela administrativa **Backups** permite configurar o horário do backup diário, backup local, envio opcional para Google Drive ou OneDrive via `rclone` e restauração de backups locais. O horário padrão é **20:00** e pode ser alterado na própria tela.

No `rclone`, cada **remoto** é uma conta configurada. Se você criar o remoto `gdrive` autenticado com uma conta Google e o remoto `onedrive` autenticado com uma conta Microsoft, a tela Backups usará a conta do remoto selecionado. Na tela, informe o remoto e a pasta, por exemplo remoto `gdrive` e pasta `MyRobotBackups/checklist`, que formam o destino `gdrive:MyRobotBackups/checklist`.

O serviço `backup` do Docker Compose executa o agendador interno e roda o backup uma vez por dia no horário configurado. Por padrão, o agendador verifica a cada 15 minutos (`BACKUP_SCHEDULER_INTERVAL_SECONDS=900`) se o horário já venceu. O script `scripts/backup.sh` continua disponível para execução manual, chamando o comando Django `run_configured_backup`.

Cada backup gera dump PostgreSQL, `media.tar.gz` quando houver arquivos locais do sistema, `.env` quando existir no container, `.env.generated` com as variáveis relevantes de runtime, configurações, seeds, scripts, configuração `rclone/` quando existir e o pacote único `backup_package.tar.gz`, que pode ser baixado ou enviado pela tela para restore. O pacote pode conter segredos e deve ser guardado em local seguro. A retenção padrão é de **30 dias** tanto local quanto na nuvem. Os diretórios `backups/` e `rclone/` ficam montados nos containers `web`/`backup` e devem continuar ignorados pelo Git.

Para restaurar, acesse **Backups**, baixe o backup da nuvem para a lista local ou envie um arquivo de backup baixado manualmente, informe novamente sua senha de administrador e confirme. Antes de substituir o banco, o sistema gera automaticamente um backup local de segurança do estado atual. Backups locais com pacote disponível também podem ser baixados pela própria tela.

Execução manual:

```bash
bash scripts/backup.sh
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

Para poucos usuários, cadastros comerciais/pedagógicos, histórico operacional textual e retenção de 1 ano ativo + 5 anos arquivados:

| Cenário | Configuração |
|---|---|
| Mínimo funcional | 2 cores, 4 GB RAM, SSD 256 GB |
| Recomendado | 4 cores, 8 GB RAM, SSD/NVMe 512 GB |
| Ideal com folga | 4 cores ou mais, 16 GB RAM, SSD/NVMe 1 TB |

O banco de dados deve crescer pouco. Sem upload de evidências operacionais, o consumo real tende a ficar concentrado no PostgreSQL e nos backups.

## Segurança operacional

- Não compartilhar usuário.
- Não expor diretamente à internet.
- Usar firewall, VPN ou rede interna.
- Trocar senhas iniciais.
- Fazer teste de restauração trimestral.
- Não guardar senhas em planilhas.
- Tratar dados de alunos, responsáveis ou crianças como informação sensível operacionalmente e restringir acesso.

<a id="english-us"></a>

## English (US)

# Checklist - My Robot Barra da Tijuca

Internal web system for operational administration at My Robot Barra da Tijuca.

The application controls access by **position**, but login is performed through **named user accounts**. This avoids generic shared logins and preserves administrative traceability.

> Current status: the old Absences, Daily Checklist, Week, History, Indicators, Activities, and Commercial modules were removed from navigation and internal routes. Legacy data/models may remain in the database for retention until the new modules are defined.

## License and Usage Disclaimer

This application is distributed under the <a href="https://www.gnu.org/licenses/gpl-3.0.html" target="_blank" rel="noopener noreferrer">GNU GPL v3</a> license.

The system was created from an internal need at the My Robot Barra da Tijuca unit to track, document, and organize the daily, weekly, and monthly activities of the unit's team members.

This project is intended for **internal use** in a controlled environment, preferably on a local network, VPN, or a server that is not publicly exposed. **Never publish this application directly on the internet without a complete technical review of security, infrastructure, privacy, and legal compliance.**

This system **is not a commercial product** sold, licensed, or guaranteed by My Robot Barra da Tijuca, its owners, or its team members. The code is provided without any warranty of operation, legal fitness, labor compliance, tax/accounting adequacy, technical reliability, security, or continuity.

Any use by other companies, franchises, units, organizations, or third parties is done **at their own risk**. Before using, adapting, or deploying this system, each organization must validate it with its technical, legal, accounting, labor, and data-protection stakeholders.

Because the system may store information about employees, students, guardians, and operational data, its use must follow good information-security practices, access control, backup, retention, and privacy rules, including LGPD where applicable.

## Additional Documentation

- [Production Test Checklist](docs/TESTE_PRODUCAO.md)
- [Annual Operation and 5-Year Retention](docs/OPERACAO_ANUAL.md)

Use the production checklist before officially releasing the system. Use the annual guide to freeze each year's instance, validate backup/restore, and start the following year.

## Profiles and Positions

The system works with two logical profiles:

- **Administrator**: creates users, resets passwords, manages types/positions, checks the audit trail, and manages backups.
- **Common/operational user**: accesses a neutral operational area and changes their own password while the new operational modules are redesigned.

Common-user types/positions are configurable, for example **Commercial Attendant**, **Free Course Instructor**, or future operational positions. Positions and users must not be physically deleted through the interface; when they are no longer valid, they are deactivated to preserve history.

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
- Administrative CRUD for user types/positions.
- Lean administrative dashboard.
- Administrative audit trail with before/after values and CSV export.
- CSV export.
- Django admin panel for advanced maintenance.
- Configurable daily backup with PostgreSQL dump, local files, and configuration files.
- Restore script.

Modules removed in this step: Absences, Daily Checklist, Week, History, Indicators, Activities, and Commercial.

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

## Installation on Ubuntu Server 26.04 LTS

Install Docker, clone this repository into `/opt/checklist`, create `.env` based on `.env.example`, adjust the environment variables, and start the application.

To install on a fresh Ubuntu Server 26.04 LTS using a packaged installer, generate the archive with:

```bash
bash scripts/build_installer_package.sh
```

Then copy the `.tar.gz` from `dist/` to the server and follow `docs/INSTALACAO_UBUNTU26.md`.

The package installs the code, but it does not automatically carry data entered on the current computer. To install on another computer while keeping records, create a full backup in **Backups** or with `docker compose exec web python manage.py run_configured_backup`, copy the generated `backup_package.tar.gz` to the new server, and restore it from **Backups**. For reinstalls on the same server, the installer preserves `.env`, the PostgreSQL volume, `media/`, `backups/`, `logs/`, `staticfiles/`, and `rclone/`, and it tries to create a local backup before updating.

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

By default, the container does not recreate the old operational activities and indicators. The command below keeps only the base operational positions:

```bash
docker compose exec web python manage.py seed_operational_data
```

## Sponte Integration

The **Pedagogical Management > Students** screen has an **Import from Sponte** button that fetches students from the SOAP `GetAlunos` endpoint.

Configure credentials only in the server `.env` file:

```env
SPONTE_API_ENABLED=False
SPONTE_API_BASE_URL=https://api.sponteeducacional.net.br/WSAPIEdu.asmx
SPONTE_API_CLIENT_CODE=
SPONTE_API_TOKEN=
SPONTE_API_TIMEOUT_SECONDS=30
SPONTE_API_CACHE_TTL_MINUTES=60
SPONTE_API_MAX_REQUESTS_PER_MINUTE=30
SPONTE_API_WAIT_ON_RATE_LIMIT=True
SPONTE_API_RATE_LIMIT_WAIT_PADDING_SECONDS=2
SPONTE_STUDENT_SEARCH_PARAMS=Nome=%
SPONTE_COURSE_SEARCH_PARAMS=Situacao=1
SPONTE_SCHEDULE_SYNC_DAYS_BACK=0
SPONTE_SCHEDULE_SYNC_DAYS_AHEAD=90
```

The system imports active and inactive students returned by Sponte, including name, enrollment number, guardian, WhatsApp, status, source, and external ID. The import creates missing students and updates existing students by `source=Sponte`/`external_id` or by enrollment number. The token is not stored in logs or audit payloads. Calls use local cache and a defensive per-minute request limit. When `SPONTE_API_WAIT_ON_RATE_LIMIT=True`, syncs wait for the next minute window instead of failing when the local limit is reached.

On **Pedagogical Management > Courses**, the **Sync Sponte** button fetches courses from the SOAP `GetCursos` endpoint. Courses with version `1.0` are ignored; when a base-name conflict exists, the Sponte version, preferably `2.0`, replaces the local record without physical deletion and preserves value/kits already configured in Checklist.

On **Pedagogical Management > Schedule**, the **Sync Sponte** button fetches each active Sponte-imported student's schedule through the SOAP `GetAgendaAluno` endpoint and uses only the **AulasLivres** section. When SOAP returns the **lesson situation**, Checklist uses the same Sponte labels: `Presença`, `Falta`, `Não dada`, and `Cancelada`. For audits and bulk corrections, export the Sponte **Aulas Livres** report as XML with Lesson Situation = All and run `reconcile_sponte_lessons --report-xml path.xml`; report data takes precedence over the local database. These regular lessons are displayed in Checklist as read-only records. Checklist continues to create only **Trial or Play Lessons** locally. Syncs started from the UI run in the background; users see one notification when the job starts and another when it finishes or fails.

When creating a **Trial or Play Lesson**, the administrator must choose whether it is `Trial` or `Play` and link it to a commercial opportunity. One opportunity may have several Trial or Play Lessons, keeping traceability for clients that do not exist in Sponte yet.

Dated Sponte synchronizations always start on the day the sync runs and move forward only. `SPONTE_SCHEDULE_SYNC_DAYS_AHEAD` controls how many future days are included in the schedule. `SPONTE_SCHEDULE_SYNC_DAYS_BACK` is kept only for compatibility and should remain `0`. If a future regular Sponte lesson no longer appears within the synced window, it is marked as cancelled in Checklist without physical deletion.

Technical details, cache policy, rate limiting, and privacy safeguards are documented in `docs/sponte_integration.md`.

## Lesson Feedback

The **Pedagogical Management > Lesson Feedback** screen replaces the previous feedback model placeholder. Checklist uses one standard feedback form for regular enrolled-student lessons.

Feedback is filled out after each regular Sponte-synced lesson. **Trial or Play Lessons do not require feedback** in this flow. Free-course instructors and administrators can access the screen.

Scores are selected from 0 to 10. Punctuality is shown as **Yes** or **No**, but it is stored internally as 10 or 5. When the lesson includes programming, the instructor enables that option and fills in the programming comment and score. If the lesson does not include programming, that score is excluded from the calculation.

The general score is calculated automatically from the provided scores and is read-only in the form.

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

Administrators can create other administrators, create operational users, define positions, reset passwords, view the administrative dashboard, export CSV files, consult the administrative audit trail, manage backups, and access the `/admin/` panel.

### Operational Users

Operational users access the system with individual user accounts and see a neutral operational area while the execution modules are redesigned.

## Daily Backup

The admin **Backups** screen lets administrators configure the daily backup time, local backup, optional upload to Google Drive or OneDrive through `rclone`, and local backup restore. The default time is **8:00 PM** and can be changed in the screen.

In `rclone`, each **remote** is a configured account. If you create a `gdrive` remote authenticated with one Google account and an `onedrive` remote authenticated with one Microsoft account, the Backups screen will use the account behind the selected remote. In the screen, enter the remote and folder, for example remote `gdrive` and folder `MyRobotBackups/checklist`, which form the destination `gdrive:MyRobotBackups/checklist`.

The Docker Compose `backup` service runs the internal scheduler and creates one backup per day at the configured time. By default, the scheduler checks every 15 minutes (`BACKUP_SCHEDULER_INTERVAL_SECONDS=900`) whether the configured time is due. The `scripts/backup.sh` script remains available for manual execution and calls the Django `run_configured_backup` command.

Each backup includes the PostgreSQL dump, `media.tar.gz` when local system files exist, `.env` when it exists in the container, `.env.generated` with the relevant runtime variables, settings, seeds, scripts, the `rclone/` configuration when present, and the single-file `backup_package.tar.gz`, which can be downloaded or uploaded in the screen for restore. The package may contain secrets and must be stored securely. The default retention is **30 days** both locally and in the cloud. The `backups/` and `rclone/` directories are mounted into the `web`/`backup` containers and must remain ignored by Git.

To restore, open **Backups**, download the cloud backup into the local list or upload a backup file downloaded manually, enter your administrator password again, and confirm. Before replacing the database, the system automatically creates a local safety backup of the current state. Local backups with an available package can also be downloaded from the same screen.

Manual execution:

```bash
bash scripts/backup.sh
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

For a small number of users, commercial/pedagogical records, textual operational records, and retention of 1 active year + 5 archived years:

| Scenario | Configuration |
|---|---|
| Functional minimum | 2 cores, 4 GB RAM, 256 GB SSD |
| Recommended | 4 cores, 8 GB RAM, 512 GB SSD/NVMe |
| Comfortable headroom | 4+ cores, 16 GB RAM, 1 TB SSD/NVMe |

The database should grow slowly. Without operational evidence uploads, storage usage should mostly be concentrated in PostgreSQL and backup packages.

## Operational Security

- Do not share user accounts.
- Do not expose directly to the internet.
- Use firewall, VPN, or an internal network.
- Change initial passwords.
- Perform quarterly restore tests.
- Do not store passwords in spreadsheets.
- Treat data from students, guardians, or children as sensitive operational information and restrict access.

