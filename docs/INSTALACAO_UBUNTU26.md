# Instalacao em Ubuntu Server 26.04 LTS

Este documento descreve a instalacao do Checklist em um servidor Ubuntu Server 26.04 LTS recem instalado.

O instalador configura Docker, Docker Compose, arquivos da aplicacao, `.env`, containers, usuario administrador inicial e diretorios persistentes. A aplicacao Django fica configurada para responder em qualquer endereco IP do servidor por padrao. O sistema ainda deve permanecer em rede interna, VPN ou firewall restritivo.

## Gerar o pacote

No ambiente de desenvolvimento:

```bash
bash scripts/build_installer_package.sh
```

O pacote sera criado em `dist/` com o formato:

```text
checklist-ubuntu26-installer-<revisao>-<data>.tar.gz
```

## Instalar no servidor

Copie o `.tar.gz` para o Ubuntu Server 26.04 e execute:

```bash
tar -xzf checklist-ubuntu26-installer-*.tar.gz
cd checklist-ubuntu26-installer-*
sudo ./install_ubuntu26.sh
```

Ao final, as credenciais iniciais ficam em:

```text
/root/checklist-credentials.txt
```

Troque a senha do usuario `checklistadmin` apos o primeiro acesso.

## Opcoes do instalador

Por padrao, a aplicacao fica disponivel em todos os enderecos IP do servidor:

```text
APP_BIND=0.0.0.0:8000
DJANGO_ALLOWED_HOSTS=*
```

O Grafana continua local por padrao, porque deve ser tratado como ferramenta administrativa:

```text
GRAFANA_BIND=127.0.0.1:3000
```

Se quiser manter a aplicacao apenas local:

```bash
sudo CHECKLIST_APP_BIND=127.0.0.1:8000 ./install_ubuntu26.sh
```

Se quiser publicar Grafana na rede administrativa protegida:

```bash
sudo CHECKLIST_GRAFANA_BIND=0.0.0.0:3000 ./install_ubuntu26.sh
```

Outras opcoes:

```bash
sudo CHECKLIST_INSTALL_DIR=/opt/checklist ./install_ubuntu26.sh
sudo CHECKLIST_RUN_OPERATIONAL_SEED=True ./install_ubuntu26.sh
sudo CHECKLIST_FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN=True ./install_ubuntu26.sh
sudo CHECKLIST_DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,meu-servidor.local ./install_ubuntu26.sh
sudo CHECKLIST_CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://meu-servidor.local:8000 ./install_ubuntu26.sh
```

`CHECKLIST_RUN_OPERATIONAL_SEED=True` importa as atividades operacionais do seed uma vez durante a instalacao. O `.env` gerado mantem `AUTO_SEED_OPERATIONAL_DATA=False` para evitar reimportacao automatica em todo restart.

## Operacao apos instalar

```bash
cd /opt/checklist
docker compose ps
docker compose logs --tail=120 web
docker compose exec web python manage.py makemigrations --check --dry-run
```

## Atualizar ou reinstalar preservando dados

Use este procedimento quando o servidor ja tem o Checklist instalado em `/opt/checklist` e voce quer aplicar um pacote novo sem apagar banco, `.env`, arquivos locais, backups ou configuracao rclone.

O banco fica no volume Docker `postgres_data`. Arquivos locais, backups, logs, arquivos estaticos e configuracao `rclone` ficam em diretorios locais montados em `/opt/checklist`. O instalador nao usa `docker compose down -v` e nao apaga esses caminhos.

Por seguranca, o instalador tenta gerar automaticamente um backup local antes de atualizar uma instalacao existente. Se esse backup falhar, a atualizacao para. Para continuar mesmo assim, use `CHECKLIST_SKIP_PRE_UPDATE_BACKUP=True` somente quando voce ja tiver um backup valido.

Voce tambem pode gerar um backup manual antes de atualizar e, se a nuvem ja estiver funcionando, confirmar o envio:

```bash
cd /opt/checklist
docker compose exec web python manage.py run_configured_backup
```

Copie o novo pacote para o servidor e execute:

```bash
tar -xzf checklist-ubuntu26-installer-*.tar.gz
cd checklist-ubuntu26-installer-*
sudo ./install_ubuntu26.sh
```

O instalador preserva estes caminhos:

```text
/opt/checklist/.env
/opt/checklist/media/
/opt/checklist/backups/
/opt/checklist/rclone/
/opt/checklist/logs/
/opt/checklist/staticfiles/
```

## Levar dados para outro computador

O pacote `checklist-ubuntu26-installer-*.tar.gz` instala codigo e infraestrutura, mas nao inclui os dados cadastrados no banco do computador atual. Para instalar em outro computador mantendo cadastros:

1. No computador atual, gere um backup completo:

```bash
cd /opt/checklist
docker compose exec web python manage.py run_configured_backup
```

2. Copie o `backup_package.tar.gz` gerado dentro de `/opt/checklist/backups/...` para o novo servidor.

3. Instale o sistema normalmente no novo servidor.

4. Acesse **Backups** como administrador, envie o `backup_package.tar.gz` pela area de restore e restaure o backup.

Depois da reinstalacao, force o rebuild e confira a versao do rclone dentro dos containers:

```bash
cd /opt/checklist
docker compose up -d --build
docker compose exec web rclone version
docker compose exec backup rclone version
```

Para OneDrive, a versao esperada deve ser a versao oficial atual do rclone, nao `v1.60.1-DEV`.

Valide upload na nuvem antes de confiar no job diario:

```bash
docker compose exec web sh -lc 'echo teste > /tmp/rclone-write-test.txt && rclone copyto /tmp/rclone-write-test.txt "onedrive-usantos:BKP/checklist/rclone-write-test.txt" -vv'
docker compose exec web rclone deletefile "onedrive-usantos:BKP/checklist/rclone-write-test.txt" -vv
docker compose exec web python manage.py run_configured_backup
```

Para configurar Google Drive ou OneDrive para backup:

```bash
cd /opt/checklist
docker compose exec web rclone config
```

Depois, acesse a tela **Backups** como administrador e selecione o remoto/conta e a pasta de destino.

## Diagnostico rclone OneDrive

Se a listagem funcionar, mas upload falhar com `unauthenticated: Unauthenticated`, valide escrita manualmente:

```bash
cd /opt/checklist
docker compose exec web sh -lc 'echo teste > /tmp/rclone-write-test.txt && rclone copyto /tmp/rclone-write-test.txt "onedrive-usantos:BKP/checklist/rclone-write-test.txt" -vv'
```

Se esse teste falhar, o problema esta no remoto/token do rclone ou na versao do rclone, nao no Checklist. A imagem do Checklist instala o rclone pelo instalador oficial para evitar versoes antigas do pacote Ubuntu/Debian.

Depois de atualizar a imagem, reconecte o remoto:

```bash
docker compose exec web rclone config reconnect onedrive-usantos:
```

Em servidor headless, responda `n` quando o rclone perguntar se deve usar auto config e autorize em uma maquina com navegador usando `rclone authorize`.
