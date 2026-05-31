# Operação Anual e Retenção por 5 anos

Este documento descreve como encerrar uma instância anual do sistema Checkups, congelar seus dados e iniciar uma nova instância para o próximo ano.

A estratégia recomendada é manter uma instância ativa por ano civil, preservando os anos anteriores como histórico consultável/restaurável.

## 1. Objetivo

- Evitar mistura de dados entre anos.
- Facilitar auditoria e consultas trabalhistas/operacionais.
- Reduzir risco de alteração acidental de histórico antigo.
- Manter backups organizados por ano.
- Preservar evidências por no mínimo 5 anos.

## 2. Estrutura recomendada de pastas

Use uma pasta por ano:

```text
/opt/checkups/2026
/opt/checkups/2027
/opt/checkups/2028
/opt/checkups/2029
/opt/checkups/2030
```

Opcionalmente, mantenha um link simbólico para a instância atual:

```text
/opt/checkups/atual -> /opt/checkups/2026
```

Exemplo:

```bash
sudo mkdir -p /opt/checkups/2026
sudo ln -sfn /opt/checkups/2026 /opt/checkups/atual
```

## 3. Convenção de nomes

Use nomes claros para containers e diretórios se for manter mais de uma instância no mesmo servidor.

Exemplo para 2026:

```text
Projeto: checkups_2026
Pasta: /opt/checkups/2026
Banco: myrobot_checklist_2026
Backup local: /opt/checkups/2026/backups
```

Para 2027:

```text
Projeto: checkups_2027
Pasta: /opt/checkups/2027
Banco: myrobot_checklist_2027
Backup local: /opt/checkups/2027/backups
```

## 4. Encerramento do ano

Executar no último dia útil do ano ou na primeira semana de janeiro, antes de iniciar a operação do novo ano.

### 4.1. Comunicar congelamento

Registrar internamente:

```text
Sistema Checkups ano AAAA será congelado em DD/MM/AAAA às HH:MM.
Após esse horário, novos lançamentos deverão ser feitos apenas na instância do ano seguinte.
```

### 4.2. Pausar uso operacional

Avisar os usuários para não registrarem novas evidências durante o processo.

### 4.3. Gerar backup final completo

Na pasta do ano:

```bash
cd /opt/checkups/2026
bash scripts/backup.sh
```

Confirmar que o backup gerou:

- dump PostgreSQL;
- pasta `media/`;
- `.env`;
- `docker-compose.yml`;
- scripts;
- seeds;
- logs relevantes;
- hash/checksum, se configurado.

### 4.4. Gerar checksum SHA256

```bash
cd /opt/checkups/2026
mkdir -p backups/checksums
sha256sum backups/*.tar.gz > backups/checksums/SHA256SUMS_2026.txt
sha256sum backups/*.sql* >> backups/checksums/SHA256SUMS_2026.txt 2>/dev/null || true
```

Guarde o arquivo `SHA256SUMS_2026.txt` junto com os backups.

### 4.5. Copiar backup para nuvem

Se `rclone` estiver configurado:

```bash
rclone copy /opt/checkups/2026/backups gdrive:MyRobotBackups/checkups/2026 --progress
```

Ou OneDrive:

```bash
rclone copy /opt/checkups/2026/backups onedrive:MyRobotBackups/checkups/2026 --progress
```

Validar:

```bash
rclone ls gdrive:MyRobotBackups/checkups/2026
```

## 5. Teste obrigatório de restauração

Antes de considerar o ano congelado, restaure em ambiente temporário.

```bash
sudo mkdir -p /opt/checkups-restore-test-2026
sudo chown -R $USER:$USER /opt/checkups-restore-test-2026
```

Copie o projeto ou clone o repositório:

```bash
cd /opt/checkups-restore-test-2026
git clone https://github.com/ussantos/checkups.git .
```

Copie ou ajuste o `.env` de teste.

Execute o restore:

```bash
./scripts/restore.sh /opt/checkups/2026/backups/NOME_DO_BACKUP_FINAL
```

Validar:

- [ ] Sistema sobe.
- [ ] Login administrativo funciona.
- [ ] Funcionários aparecem.
- [ ] Histórico do ano aparece.
- [ ] Evidências abrem.
- [ ] CSV exporta dados.
- [ ] Dashboard mensal abre.

Registrar resultado:

```text
Ano:
Backup testado:
Data do teste:
Responsável:
Resultado: aprovado / aprovado com ressalvas / reprovado
Observações:
```

## 6. Tornar a instância antiga somente consulta

Existem três opções.

### Opção A — Desligar e manter apenas backup

Mais simples e econômica.

```bash
cd /opt/checkups/2026
docker compose down
```

Use quando o histórico só precisa ser restaurado sob demanda.

### Opção B — Manter online somente para consulta

Útil se você precisar consultar com frequência.

Recomendações:

- remover ou bloquear usuários operacionais;
- manter apenas administradores;
- colocar aviso no README/local: “Instância congelada — somente consulta”; 
- não usar para registros novos;
- manter porta diferente da instância atual.

Exemplo de `.env` para consulta:

```env
APP_BIND=127.0.0.1:8026
```

### Opção C — Exportar relatórios e desligar

Gerar CSVs anuais, guardar com backup e desligar.

Exportar:

```text
/relatorio/historico.csv
/relatorio/mensal.csv?ano=2026&mes=01
...
/relatorio/mensal.csv?ano=2026&mes=12
```

## 7. Criar nova instância para o próximo ano

Exemplo para 2027:

```bash
sudo mkdir -p /opt/checkups/2027
sudo chown -R $USER:$USER /opt/checkups/2027
cd /opt/checkups/2027
git clone https://github.com/ussantos/checkups.git .
cp .env.example .env
nano .env
```

Ajustar no `.env`:

```env
POSTGRES_DB=myrobot_checklist_2027
APP_BIND=127.0.0.1:8000
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,IP_DO_SERVIDOR
CSRF_TRUSTED_ORIGINS=http://IP_DO_SERVIDOR:8000
```

Subir:

```bash
docker compose up -d --build
```

Validar usando `docs/TESTE_PRODUCAO.md`.

## 8. Atualizar link simbólico da instância atual

Se usar link simbólico:

```bash
sudo ln -sfn /opt/checkups/2027 /opt/checkups/atual
```

## 9. Rotina de retenção por 5 anos

Manter:

```text
Ano atual: online e ativo
Ano anterior: online consulta ou backup restaurável
Anos 2 a 5: backup restaurável + relatórios exportados
Mais de 5 anos: avaliar com contabilidade/jurídico antes de excluir
```

Recomendação prudente: antes de apagar qualquer histórico, validar com contabilidade ou assessoria trabalhista, especialmente se houver documentos que possam servir como prova de jornada, tarefas, treinamentos, incidentes ou evidências relacionadas a empregados.

## 10. Organização dos backups na nuvem

Estrutura recomendada:

```text
MyRobotBackups/
└── checkups/
    ├── 2026/
    │   ├── backups/
    │   ├── checksums/
    │   └── relatorios_csv/
    ├── 2027/
    ├── 2028/
    ├── 2029/
    └── 2030/
```

## 11. Teste trimestral de restauração

Mesmo com backup diário, execute restauração de teste pelo menos a cada trimestre.

Agenda sugerida:

- Março
- Junho
- Setembro
- Dezembro

Registrar:

```text
Data:
Backup usado:
Ambiente de restauração:
Responsável:
Resultado:
Pendências:
```

## 12. Checklist anual resumido

- [ ] Comunicar congelamento aos usuários.
- [ ] Parar lançamentos no ano antigo.
- [ ] Gerar backup final.
- [ ] Gerar checksum SHA256.
- [ ] Copiar backup para nuvem.
- [ ] Testar restauração.
- [ ] Exportar CSVs anuais, se necessário.
- [ ] Desligar ou restringir instância antiga.
- [ ] Criar instância do novo ano.
- [ ] Testar nova instância.
- [ ] Atualizar cron de backup.
- [ ] Atualizar documentação interna.

## 13. Observação trabalhista e LGPD

Os dados podem conter informações de empregados, alunos, responsáveis, imagens, prints, evidências de atendimento e documentos operacionais.

Portanto:

- restrinja acesso aos administradores;
- não compartilhe backups sem necessidade;
- proteja a conta de nuvem com MFA;
- não envie backups por WhatsApp ou e-mail comum;
- mantenha registro de quem acessa restaurações;
- valide descarte de dados com contabilidade/jurídico quando houver dúvida.
