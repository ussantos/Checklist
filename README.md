# Checklist — My Robot Barra da Tijuca

Sistema web interno para controle de checklist/checklists operacionais da My Robot Barra da Tijuca.

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

O sistema trabalha com três tipos de usuário:

- **Administrador**: acompanha todos os cargos, cadastra usuários, redefine senhas e acessa relatórios gerais.
- **Atendente Comercial**: executa o checklist comercial.
- **Instrutor de Aula Livre**: executa o checklist pedagógico.

## Funcionamento de usuários

- O primeiro usuário da aplicação é o administrador técnico `checklistadmin`.
- O `checklistadmin` é criado automaticamente pelo seed inicial.
- A partir dele, devem ser cadastrados usuários nominais com uma das funções: **Administrador**, **Atendente Comercial** ou **Instrutor de Aula Livre**.
- Não há usuários operacionais genéricos para execução diária.
- No cadastro, o administrador informa nome completo, usuário de login, e-mail opcional, função/perfil e senha forte.
- A tela **Trocar senha** funciona para qualquer tipo de usuário: administrador, atendente ou instrutor.

## Regras de senha forte

A senha deve ter pelo menos 12 caracteres, uma letra maiúscula, uma letra minúscula, um número e um caractere especial.

## Recursos principais

- Login local.
- Cadastro nominal de usuários por administradores.
- Criação de usuários com função de Administrador, Atendente Comercial ou Instrutor de Aula Livre.
- Checklist diário por cargo.
- Visão semanal por dia útil.
- Dashboard mensal.
- Histórico filtrável.
- Exportação CSV.
- Evidência textual por atividade.
- Upload de múltiplos arquivos por atividade.
- Suporte a PDF, imagens, prints e fotos.
- Identificação automática do usuário logado em cada lançamento.
- Anexos protegidos por login e permissão no cargo.
- Painel administrativo Django para manutenção avançada.
- Backup diário às 20h com dump PostgreSQL, arquivos de evidência e configurações.
- Script de restauração.

## Status das atividades

- Previsto
- Em andamento
- Concluído
- Não se aplica
- Bloqueado/Pendente

Ao marcar uma tarefa como **Concluído**, o sistema exige evidência textual ou pelo menos um arquivo anexado. Para **Bloqueado/Pendente**, o sistema exige motivo.

## Evidências aceitas

Extensões aceitas por padrão: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` e `.heic`.

O limite de tamanho é definido no `.env` pela variável `MAX_EVIDENCE_FILE_SIZE_MB`.

## Arquitetura

- Python 3.12
- Django
- PostgreSQL
- Gunicorn
- WhiteNoise para arquivos estáticos
- Docker Compose
- Backup via `pg_dump` + `rclone`

## Estrutura simplificada

```text
.
├── checklists/                 # App principal Django
├── docs/                       # Documentação operacional e testes
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

Ver logs:

```bash
docker compose logs -f web
```

Acesse pelo endereço configurado no servidor, por exemplo:

```text
http://IP_DO_SERVIDOR:8000
```

Antes de liberar uso oficial, execute os testes em `docs/TESTE_PRODUCAO.md`.

## Uso operacional

### Administradores

Usuários administradores podem cadastrar outros administradores, cadastrar usuários operacionais, definir cargo, redefinir senha, visualizar dashboards, filtrar histórico, exportar CSV, revisar evidências e acessar o painel `/admin/`.

### Usuários operacionais

Atendentes Comerciais e Instrutores de Aula Livre acessam o sistema com usuário individual. O sistema mostra as tarefas de acordo com o cargo cadastrado e grava automaticamente o nome do usuário logado no histórico.

## Backup diário às 20h

O script `scripts/backup.sh` gera backup do banco PostgreSQL, da pasta `media/`, do `.env`, configurações, seeds e scripts. O envio para Google Drive ou OneDrive pode ser feito via `rclone`.

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

