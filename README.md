# Checkups — My Robot Barra da Tijuca

Sistema web interno para controle de checkups/checklists operacionais da My Robot Barra da Tijuca.

A aplicação controla a rotina por **cargo**, mas o acesso é feito por **usuário nominal**. Isso evita uso de login genérico e preserva evidência trabalhista/operacional: cada lançamento fica associado ao funcionário logado e ao cargo exercido.

## Documentação complementar

- [Checklist de Teste de Produção](docs/TESTE_PRODUCAO.md)
- [Operação Anual e Retenção por 5 anos](docs/OPERACAO_ANUAL.md)

Use o checklist de produção antes de liberar o sistema oficialmente. Use o guia anual para congelar a instância de cada ano, validar backup/restauração e iniciar o ano seguinte.

## Cargos operacionais

- Atendente Comercial
- Instrutor de Aula Livre

## Funcionamento de usuários

- Administradores iniciais: `uellington` e `liliane`.
- Funcionários não são criados como usuários genéricos.
- Funcionários devem ser cadastrados na tela **Funcionários**.
- No cadastro, o administrador informa:
  - nome completo;
  - usuário de login;
  - e-mail, opcional;
  - cargo: Atendente Comercial ou Instrutor de Aula Livre;
  - senha forte.
- Cada funcionário pode trocar a própria senha pelo menu **Trocar senha**.

## Regras de senha forte

A senha deve ter:

- pelo menos 12 caracteres;
- pelo menos uma letra maiúscula;
- pelo menos uma letra minúscula;
- pelo menos um número;
- pelo menos um caractere especial.

Essas regras são aplicadas tanto no cadastro feito pelo administrador quanto na troca de senha pelo próprio funcionário.

## Recursos principais

- Login local.
- Cadastro nominal de funcionários por administradores.
- Checklist diário por cargo.
- Visão semanal por dia útil.
- Dashboard mensal.
- Histórico filtrável.
- Exportação CSV.
- Evidência textual por atividade.
- Upload de múltiplos arquivos por atividade.
- Suporte a PDF, imagens, prints e fotos.
- Identificação automática do funcionário logado em cada lançamento.
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

Extensões aceitas por padrão:

- `.pdf`
- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.gif`
- `.heic`

O limite de tamanho é definido no `.env`:

```env
MAX_EVIDENCE_FILE_SIZE_MB=15
```

## Arquitetura

- Python 3.12
- Django
- PostgreSQL
- Gunicorn
- WhiteNoise para arquivos estáticos
- Docker Compose
- Backup via `pg_dump` + `rclone`

Estrutura simplificada:

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

### 1. Instalar Docker

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Saia e entre novamente na sessão SSH para aplicar o grupo `docker`.

### 2. Clonar o repositório

```bash
sudo mkdir -p /opt/checkups
sudo chown -R $USER:$USER /opt/checkups
cd /opt/checkups
git clone https://github.com/ussantos/checkups.git .
```

### 3. Criar o `.env`

```bash
cp .env.example .env
nano .env
```

Altere principalmente:

```env
DJANGO_SECRET_KEY=troque-por-uma-chave-grande-e-aleatoria
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,IP_DO_SERVIDOR
CSRF_TRUSTED_ORIGINS=http://IP_DO_SERVIDOR:8000
APP_BIND=127.0.0.1:8000
POSTGRES_PASSWORD=troque-esta-senha
INITIAL_UELLINGTON_PASSWORD=Trocar@Senha2026
INITIAL_LILIANE_PASSWORD=Trocar@Senha2026
MAX_EVIDENCE_FILE_SIZE_MB=15
```

Para acesso apenas local no próprio servidor:

```env
APP_BIND=127.0.0.1:8000
```

Para acesso pela rede interna ou VPN:

```env
APP_BIND=0.0.0.0:8000
```

Se usar `0.0.0.0`, proteja com firewall e libere apenas a rede interna/VPN.

### 4. Subir o sistema

```bash
docker compose up -d --build
```

Ver logs:

```bash
docker compose logs -f web
```

Acessar:

```text
http://IP_DO_SERVIDOR:8000
```

### 5. Homologar antes de usar

Execute os testes de homologação antes de liberar uso oficial:

```text
docs/TESTE_PRODUCAO.md
```

## Uso operacional

### Administradores

Usuários `uellington` e `liliane` podem:

- cadastrar funcionários;
- definir cargo do funcionário;
- redefinir senha de funcionário;
- visualizar todos os cargos;
- acompanhar dashboard mensal;
- filtrar histórico;
- exportar CSV;
- editar tarefas e indicadores pelo `/admin/`;
- revisar evidências anexadas.

### Funcionários

1. Acessar o sistema com usuário individual.
2. Abrir **Checklist do dia**.
3. O sistema mostra as tarefas de acordo com o cargo cadastrado.
4. Em cada atividade, registrar:
   - status;
   - evidência textual;
   - anexos em PDF ou imagem, quando houver;
   - motivo, se ficar bloqueado/pendente.
5. O nome do funcionário logado é gravado automaticamente no histórico.

## Backup diário às 20h

O script `scripts/backup.sh` gera:

- dump do banco PostgreSQL;
- cópia da pasta `media/`, onde ficam as evidências;
- cópia de `.env`, `docker-compose.yml`, `seed/` e `scripts/`;
- envio opcional para Google Drive ou OneDrive via `rclone`.

Agendamento no cron:

```bash
crontab -e
```

Adicionar:

```cron
0 20 * * * cd /opt/checkups && /bin/bash scripts/backup.sh >> logs/backup.log 2>&1
```

## Restauração

Exemplo:

```bash
cd /opt/checkups
./scripts/restore.sh /caminho/do/backup/2026-12-31_200000
```

Antes de considerar o backup confiável, faça teste de restauração conforme:

```text
docs/TESTE_PRODUCAO.md
```

## Encerramento anual da instância

Para congelar o ano, validar backup/restauração e iniciar uma nova instância, siga:

```text
docs/OPERACAO_ANUAL.md
```

Recomendação para controle anual:

```text
/opt/checkups/2026
/opt/checkups/2027
/opt/checkups/2028
```

No fim do ano:

1. parar a instância do ano;
2. gerar backup final completo;
3. validar restauração em pasta temporária;
4. gerar checksum SHA256 do backup;
5. marcar a instância como somente consulta;
6. iniciar nova instância para o ano seguinte.

Exemplo de backup final:

```bash
cd /opt/checkups/2026
./scripts/backup.sh
sha256sum backups/*.tar.gz > backups/SHA256SUMS.txt
```

Mantenha os backups anuais por pelo menos 5 anos em dois locais: servidor/local e nuvem.

## Configuração recomendada do computador/servidor

Para a operação descrita — poucos usuários, checklists diários, evidências em PDF/imagem e retenção de 1 ano ativo + 5 anos arquivados — recomenda-se:

### Mínimo funcional

- CPU: 2 cores.
- RAM: 4 GB.
- Disco SSD: 256 GB.
- Sistema: Ubuntu 24.04 LTS.
- Backup externo/nuvem obrigatório.

### Recomendado

- CPU: 4 cores.
- RAM: 8 GB.
- Disco SSD/NVMe: 512 GB.
- Backup diário para Google Drive/OneDrive.
- Nobreak, se estiver em computador físico na loja.

### Ideal para 5 anos com folga

- CPU: 4 cores ou mais.
- RAM: 16 GB.
- Disco SSD/NVMe: 1 TB.
- Backup em nuvem + cópia local externa.

O banco de dados deve crescer pouco. O consumo real virá principalmente dos anexos de evidência. Se cada ano gerar entre 20 GB e 60 GB de evidências, 5 anos podem consumir entre 100 GB e 300 GB apenas de anexos, sem contar backups duplicados e margem de segurança.

## Segurança operacional

- Não compartilhar usuário.
- Não expor diretamente à internet.
- Usar firewall, VPN ou rede interna.
- Trocar senhas iniciais.
- Fazer teste de restauração trimestral.
- Não guardar senhas em planilhas.
- Se houver dados de alunos, responsáveis ou crianças em evidências, tratar como informação sensível operacionalmente e restringir acesso.
