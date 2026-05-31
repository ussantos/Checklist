# Checklist de Teste de Produção

Este documento deve ser usado antes de colocar o sistema Checkups em uso oficial na My Robot Barra da Tijuca.

O objetivo é validar instalação, autenticação, cadastro de funcionários, checklists, evidências, relatórios, backup e restauração.

## 1. Pré-requisitos do servidor

Confirmar:

- [ ] Ubuntu 24.04 LTS instalado.
- [ ] Servidor atualizado com `sudo apt update && sudo apt upgrade -y`.
- [ ] Docker instalado.
- [ ] Usuário operacional adicionado ao grupo `docker`.
- [ ] Projeto clonado em `/opt/checkups`.
- [ ] Arquivo `.env` criado a partir de `.env.example`.
- [ ] `DJANGO_SECRET_KEY` trocada por chave forte.
- [ ] `POSTGRES_PASSWORD` trocada por senha forte.
- [ ] `DJANGO_DEBUG=False`.
- [ ] `DJANGO_ALLOWED_HOSTS` ajustado para `localhost`, `127.0.0.1` e IP/hostname real do servidor.
- [ ] `CSRF_TRUSTED_ORIGINS` ajustado para a URL real de acesso.
- [ ] `APP_BIND` definido conforme estratégia de acesso: `127.0.0.1:8000` ou `0.0.0.0:8000`.
- [ ] Firewall configurado.
- [ ] Acesso não exposto diretamente à internet, salvo por VPN/firewall.

## 2. Subida inicial da aplicação

Executar:

```bash
cd /opt/checkups
docker compose up -d --build
```

Validar:

```bash
docker compose ps
docker compose logs -f web
```

Confirmar:

- [ ] Container `myrobot_checklist_db` está saudável.
- [ ] Container `myrobot_checklist_web` está em execução.
- [ ] Não há erro de migração.
- [ ] Não há erro de conexão com PostgreSQL.
- [ ] Arquivos estáticos foram coletados.
- [ ] Seeds iniciais foram carregados.

## 3. Teste de login administrativo

Acessar:

```text
http://IP_DO_SERVIDOR:8000
```

Validar com o usuário `uellington`:

- [ ] Login funciona.
- [ ] Dashboard abre.
- [ ] Menu administrativo aparece.
- [ ] Menu **Funcionários** aparece.
- [ ] Menu **Histórico** aparece.
- [ ] Menu **Métricas** aparece.
- [ ] Link para `/admin/` funciona.

Repetir com o usuário `liliane`:

- [ ] Login funciona.
- [ ] Permissões administrativas estão corretas.

## 4. Cadastro de funcionário nominal

Como administrador, acessar **Funcionários > Cadastrar funcionário**.

Criar um funcionário de teste:

```text
Nome completo: Funcionário Teste Comercial
Usuário: teste.comercial
Cargo: Atendente Comercial
Senha: Teste@Senha2026
```

Validar:

- [ ] O cadastro exige senha forte.
- [ ] Senha fraca é rejeitada.
- [ ] Usuário duplicado é rejeitado.
- [ ] Funcionário aparece na lista.
- [ ] Cargo aparece corretamente.
- [ ] Funcionário pode ser editado.
- [ ] Senha pode ser redefinida pelo administrador.

Criar outro funcionário de teste:

```text
Nome completo: Funcionário Teste Instrutor
Usuário: teste.instrutor
Cargo: Instrutor de Aula Livre
Senha: Teste@Senha2026
```

Validar os mesmos itens.

## 5. Teste de troca de senha pelo funcionário

Entrar com `teste.comercial`.

Validar:

- [ ] Login funciona.
- [ ] O funcionário visualiza somente tarefas do cargo dele.
- [ ] O menu **Trocar senha** aparece.
- [ ] Senha fraca é rejeitada.
- [ ] Senha forte é aceita.
- [ ] Após trocar senha, login novo funciona.

Repetir com `teste.instrutor`.

## 6. Checklist diário

Com `teste.comercial`, abrir **Checklist do dia**.

Validar:

- [ ] Tarefas do cargo **Atendente Comercial** aparecem.
- [ ] Não aparecem tarefas do cargo **Instrutor de Aula Livre**.
- [ ] É possível alterar status para **Em andamento**.
- [ ] É possível salvar evidência textual.
- [ ] Ao concluir sem evidência textual e sem anexo, o sistema bloqueia.
- [ ] Ao concluir com evidência textual, o sistema salva.
- [ ] Ao concluir com anexo PDF, o sistema salva.
- [ ] Ao concluir com imagem, o sistema salva.
- [ ] Ao marcar como **Bloqueado/Pendente**, o sistema exige motivo.
- [ ] O nome do funcionário logado aparece no histórico da atividade.

Com `teste.instrutor`, repetir a validação para o cargo **Instrutor de Aula Livre**.

## 7. Teste de uploads de evidência

Testar anexos:

- [ ] PDF pequeno.
- [ ] PNG.
- [ ] JPG/JPEG.
- [ ] WEBP.
- [ ] Múltiplos arquivos no mesmo lançamento.
- [ ] Arquivo acima do limite configurado em `MAX_EVIDENCE_FILE_SIZE_MB` é rejeitado.
- [ ] Arquivo com extensão não permitida é rejeitado.

Testar segurança:

- [ ] Usuário deslogado não acessa anexo.
- [ ] Funcionário de outro cargo não acessa anexo sem permissão.
- [ ] Administrador acessa anexos de todos os cargos.

## 8. Visão semanal

Validar:

- [ ] A visão semanal mostra segunda a sexta.
- [ ] Tarefas aparecem nos dias corretos.
- [ ] Tarefas quinzenais aparecem apenas na quinzena configurada.
- [ ] Tarefas mensais aparecem conforme regra definida.
- [ ] Administrador consegue alternar cargo.
- [ ] Funcionário operacional enxerga apenas seu cargo.

## 9. Dashboard mensal

Como administrador:

- [ ] Dashboard mensal carrega.
- [ ] Indicadores de concluídas, pendentes e bloqueadas aparecem.
- [ ] Filtro de mês/ano funciona.
- [ ] Filtro por cargo funciona.
- [ ] Tarefas vencidas aparecem corretamente.

Como funcionário:

- [ ] Dashboard mostra apenas o cargo vinculado.

## 10. Histórico e exportações

Validar:

- [ ] Histórico carrega.
- [ ] Filtro por data funciona.
- [ ] Filtro por status funciona.
- [ ] Filtro por cargo funciona para administradores.
- [ ] Busca por texto funciona.
- [ ] Exportação CSV mensal funciona.
- [ ] Exportação CSV de histórico funciona.
- [ ] CSV abre corretamente no Excel/LibreOffice.
- [ ] CSV contém funcionário executor, cargo, status, evidência textual e anexos.

## 11. Métricas operacionais

Validar:

- [ ] Métrica pode ser registrada por cargo.
- [ ] Métrica aceita valor numérico.
- [ ] Métrica aceita observação.
- [ ] Métrica aceita anexo, se aplicável.
- [ ] Métricas aparecem no dashboard.
- [ ] Funcionário só vê métricas do próprio cargo.

## 12. Painel administrativo Django

Acessar `/admin/`.

Validar:

- [ ] Login administrativo funciona.
- [ ] É possível visualizar usuários.
- [ ] É possível visualizar perfis.
- [ ] É possível visualizar cargos.
- [ ] É possível visualizar modelos de tarefas.
- [ ] É possível visualizar execuções de tarefas.
- [ ] É possível visualizar anexos de evidência.
- [ ] Usuários operacionais não acessam `/admin/`.

## 13. Backup manual

Executar:

```bash
cd /opt/checkups
mkdir -p logs
bash scripts/backup.sh
```

Validar:

- [ ] Backup do banco foi gerado.
- [ ] Backup da pasta `media/` foi gerado.
- [ ] Backup do `.env` foi gerado.
- [ ] Backup de scripts/seed/configurações foi gerado.
- [ ] Log não tem erro.
- [ ] Arquivo foi enviado para o remoto `rclone`, se configurado.

## 14. Cron de backup

Configurar:

```bash
crontab -e
```

Adicionar:

```cron
0 20 * * * cd /opt/checkups && /bin/bash scripts/backup.sh >> logs/backup.log 2>&1
```

Validar no dia seguinte:

- [ ] `logs/backup.log` foi criado.
- [ ] Backup rodou às 20h.
- [ ] Arquivos apareceram na pasta de backup.
- [ ] Arquivos apareceram no Google Drive/OneDrive, se configurado.

## 15. Teste de restauração

Nunca validar produção sem teste de restauração.

Criar pasta temporária:

```bash
sudo mkdir -p /opt/checkups-restore-test
sudo chown -R $USER:$USER /opt/checkups-restore-test
```

Copiar o projeto ou clonar novamente. Depois executar o restore usando um backup real:

```bash
cd /opt/checkups-restore-test
./scripts/restore.sh /caminho/do/backup/AAAA-MM-DD_HHMMSS
```

Validar:

- [ ] Sistema sobe após restauração.
- [ ] Usuários restaurados conseguem login.
- [ ] Histórico aparece.
- [ ] Evidências anexadas aparecem.
- [ ] CSV exporta dados restaurados.
- [ ] Dashboard bate com dados esperados.

## 16. Validação final antes de liberar uso

Liberar uso somente se todos estes itens estiverem OK:

- [ ] Administradores testados.
- [ ] Funcionários nominais testados.
- [ ] Senha forte validada.
- [ ] Upload de PDF testado.
- [ ] Upload de imagem testado.
- [ ] Acesso a evidências protegido.
- [ ] Histórico e CSV testados.
- [ ] Backup manual testado.
- [ ] Cron configurado.
- [ ] Restauração testada.
- [ ] Firewall/rede interna revisados.
- [ ] `.env` não foi enviado ao GitHub.
- [ ] Credenciais iniciais foram trocadas.

## 17. Registro da homologação

Preencher após teste:

```text
Data do teste:
Responsável técnico:
Servidor/IP:
Versão/commit:
Backup testado? (sim/não):
Restauração testada? (sim/não):
Pendências encontradas:
Decisão: aprovado / aprovado com ressalvas / reprovado
```
