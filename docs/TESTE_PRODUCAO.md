# Checklist de Teste de Produção

Este documento deve ser usado antes de colocar o sistema Checklist em uso oficial na My Robot Barra da Tijuca.

O objetivo é validar instalação, autenticação, cadastro de usuários, atividades, indicadores, metas, evidências, auditoria, backup e restauração.

## 1. Pré-requisitos do servidor

Confirmar:

- [ ] Ubuntu 24.04 LTS instalado.
- [ ] Servidor atualizado com `sudo apt update && sudo apt upgrade -y`.
- [ ] Docker instalado.
- [ ] Usuário operacional adicionado ao grupo `docker`.
- [ ] Projeto clonado em `/opt/checklist`.
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
cd /opt/checklist
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

Validar com o usuário técnico `checklistadmin` ou com um administrador nominal criado para homologação:

- [ ] Login funciona.
- [ ] Dashboard abre.
- [ ] Menu administrativo aparece.
- [ ] Menu **Usuários** aparece.
- [ ] Menu **Histórico** aparece.
- [ ] Menu **Indicadores** aparece.
- [ ] Menu **Auditoria** aparece.
- [ ] Link para `/admin/` funciona.

Repetir com outro administrador nominal, se existir:

- [ ] Login funciona.
- [ ] Permissões administrativas estão corretas.

## 4. Cadastro de usuário nominal

Como administrador, acessar **Usuários > Cadastrar usuário**.

Criar um usuário comum de teste:

```text
Nome completo: Funcionário Teste Comercial
Usuário: teste.comercial
Perfil/cargo: Atendente Comercial ou outro cargo operacional ativo
```

Validar:

- [ ] O administrador não digita senha manualmente.
- [ ] O sistema gera senha temporária forte automaticamente.
- [ ] A senha temporária é exibida uma única vez.
- [ ] A senha não aparece no histórico/auditoria.
- [ ] Usuário duplicado é rejeitado.
- [ ] Usuário aparece na lista.
- [ ] Cargo aparece corretamente.
- [ ] Usuário pode ser editado.
- [ ] Senha pode ser redefinida pelo administrador.
- [ ] Usuário pode ser desativado sem exclusão física.

Criar outro usuário comum de teste:

```text
Nome completo: Funcionário Teste Instrutor
Usuário: teste.instrutor
Perfil/cargo: Instrutor de Cursos Livres ou outro cargo operacional ativo
```

Validar os mesmos itens.

## 5. Teste de troca de senha pelo usuário comum

Entrar com `teste.comercial`.

Validar:

- [ ] Login funciona.
- [ ] O usuário visualiza somente atividades do cargo dele.
- [ ] O menu **Trocar senha** aparece.
- [ ] Senha fraca é rejeitada.
- [ ] Senha forte é aceita.
- [ ] Após trocar senha, login novo funciona.
- [ ] Se `FORCE_PASSWORD_CHANGE_ON_FIRST_LOGIN=True`, o usuário é redirecionado para troca de senha no primeiro login.

Repetir com `teste.instrutor`.

## 6. Atividades do usuário comum

Com `teste.comercial`, abrir **Atividades**.

Validar:

- [ ] A tela inicial do usuário comum abre em **Atividades da semana**.
- [ ] O filtro muda automaticamente entre dia, semana e mês.
- [ ] As atividades aparecem em lógica de calendário.
- [ ] Atividades do cargo **Atendente Comercial** aparecem.
- [ ] Não aparecem atividades do cargo **Instrutor de Cursos Livres**.
- [ ] Cards ficam ordenados por horário de início.
- [ ] É possível abrir uma atividade e alterar status para **Executando**.
- [ ] É possível salvar evidência textual.
- [ ] Se a atividade exigir evidência, concluir sem evidência textual e sem anexo é bloqueado.
- [ ] Se a atividade não exigir evidência, os campos de evidência não aparecem.
- [ ] Ao concluir com evidência textual, o sistema salva.
- [ ] Ao concluir com anexo PDF, o sistema salva.
- [ ] Ao concluir com imagem, o sistema salva.
- [ ] Ao marcar como **Atrasada**, o sistema exige observação operacional.
- [ ] O nome do usuário logado aparece no histórico da atividade.

Com `teste.instrutor`, repetir a validação para o cargo **Instrutor de Cursos Livres** ou cargo equivalente.

## 7. Sugestões de atividades

Com usuário comum:

- [ ] Sugerir nova atividade abre formulário com campos de atividade.
- [ ] Sugerir desativação mostra apenas atividades ativas do cargo do usuário.
- [ ] A solicitação enviada não altera atividade imediatamente.

Com administrador:

- [ ] Sugestões aparecem na tela **Atividades**.
- [ ] Administrador consegue aprovar criação, ajustando campos antes.
- [ ] Administrador consegue rejeitar criação sem criar atividade.
- [ ] Administrador consegue aprovar desativação sem excluir histórico.
- [ ] ActivityLog registra aprovação/rejeição.

## 8. Teste de uploads de evidência

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

## 9. Visões de calendário

Validar:

- [ ] A visão semanal mostra segunda a sexta.
- [ ] Tarefas aparecem nos dias corretos.
- [ ] Tarefas quinzenais aparecem apenas na quinzena configurada.
- [ ] Tarefas mensais aparecem conforme regra definida.
- [ ] Administrador consegue alternar cargo.
- [ ] Usuário operacional enxerga apenas seu cargo.

## 10. Dashboard administrativo e indicadores/metas

Como administrador:

- [ ] Dashboard administrativo carrega.
- [ ] Filtros diário, semanal, mensal e anual funcionam.
- [ ] Indicadores, metas, realizado e percentual aparecem.
- [ ] Visão por usuário aparece quando houver mais de um usuário no mesmo cargo.
- [ ] Totalizador por tipo/cargo aparece.

Como usuário comum:

- [ ] Tela **Indicadores** mostra apenas indicadores/metas do próprio escopo.
- [ ] Botão de adicionar indicador não aparece.
- [ ] Filtro de período atualiza a tela automaticamente.

## 11. Histórico, auditoria e exportações

Validar:

- [ ] Histórico carrega.
- [ ] Filtro por data funciona.
- [ ] Filtro por status funciona.
- [ ] Filtro por cargo funciona para administradores.
- [ ] Busca por texto funciona.
- [ ] Exportação CSV mensal funciona.
- [ ] Exportação CSV de histórico funciona.
- [ ] Auditoria administrativa carrega.
- [ ] Filtros de auditoria por data, administrador, tipo de objeto, ação e texto livre funcionam.
- [ ] Exportação CSV da auditoria funciona.
- [ ] Alterações de cargo, usuário, atividade, indicador/meta e importação XLSX aparecem na auditoria.
- [ ] Redefinição de senha aparece na auditoria sem exibir senha.
- [ ] CSV abre corretamente no Excel/LibreOffice.
- [ ] CSV de histórico contém usuário executor, cargo, status, evidência textual e anexos.

## 12. Indicadores operacionais

Validar:

- [ ] Administrador cria indicador.
- [ ] Administrador vincula indicador a tipo/cargo.
- [ ] Administrador vincula indicador a atividade do tipo escolhido.
- [ ] Administrador edita meta (`monthly_target`).
- [ ] Administrador inativa indicador sem exclusão física.
- [ ] Indicador aceita evidência TXT, planilha, PDF, imagem ou arquivo similar quando registrado pelo administrador.
- [ ] Indicadores aparecem no dashboard.
- [ ] Usuário comum só vê indicadores do próprio escopo.

## 13. CRUDs administrativos sem delete físico

Validar:

- [ ] Tipo/cargo pode ser criado, editado, ativado e inativado.
- [ ] Atividade pode ser criada, editada, ativada e inativada.
- [ ] Indicador pode ser criado, editado, ativado e inativado.
- [ ] Usuário pode ser criado, editado, ativado e desativado.
- [ ] Interface interna não oferece exclusão física desses cadastros históricos.
- [ ] Cargos inativos não aparecem para novos usuários comuns.
- [ ] Atividades inativas não aparecem para usuários comuns.

## 14. Importação XLSX de atividades

Validar:

- [ ] Admin baixa modelo XLSX.
- [ ] Admin importa XLSX válido.
- [ ] XLSX inválido mostra erros por linha.
- [ ] Atividades importadas aparecem no CRUD.
- [ ] Atividades importadas aparecem para usuário comum conforme cargo e recorrência.
- [ ] Importação registra ActivityLog.

## 15. Painel administrativo Django

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

## 16. Backup manual

Antes de testar envio para Google Drive ou OneDrive, configurar o `rclone` no container:

```bash
docker compose exec web rclone config
```

Cada remoto do `rclone` representa uma conta Google Drive ou OneDrive. Depois, acessar **Backups** no sistema como administrador, escolher o destino, informar o remoto/conta e a pasta de destino.

Executar:

```bash
cd /opt/checklist
mkdir -p logs
bash scripts/backup.sh
```

Validar:

- [ ] Backup do banco foi gerado.
- [ ] Backup da pasta `media/` foi gerado, incluindo arquivos de evidência.
- [ ] Backup do `.env` foi gerado.
- [ ] Backup de scripts/seed/configurações foi gerado.
- [ ] Pacote `backup_package.tar.gz` foi gerado.
- [ ] Log não tem erro.
- [ ] Arquivo foi enviado para o remoto `rclone`, se configurado.

## 16.1. Restore pela tela Backups

Na tela **Backups**, validar:

- [ ] Backups locais aparecem na tabela.
- [ ] A tela exige digitar `RESTAURAR` antes de restaurar.
- [ ] Antes do restore, um novo backup local de segurança é gerado automaticamente.
- [ ] Restore de banco conclui sem erro.
- [ ] Restore de mídia pode ser marcado/desmarcado.
- [ ] Upload de `backup_package.tar.gz` baixado da nuvem importa o backup para a lista local.
- [ ] Após restore, login, usuários, atividades, indicadores e anexos são validados.

## 17. Agendador de backup

Validar o serviço interno:

```bash
docker compose ps backup
```

Na tela **Backups**:

- [ ] Horário padrão está em 20:00.
- [ ] Horário pode ser alterado e salvo.
- [ ] Retenção local/nuvem está em 30 dias.
- [ ] Serviço `backup` está rodando.

Validar no dia seguinte:

- [ ] Backup rodou no horário configurado.
- [ ] Arquivos apareceram na pasta de backup.
- [ ] Arquivos apareceram no Google Drive/OneDrive, se configurado.

## 18. Teste de restauração

Nunca validar produção sem teste de restauração.

Criar pasta temporária:

```bash
sudo mkdir -p /opt/checklist-restore-test
sudo chown -R $USER:$USER /opt/checklist-restore-test
```

Copiar o projeto ou clonar novamente. Depois executar o restore usando um backup real:

```bash
cd /opt/checklist-restore-test
./scripts/restore.sh /caminho/do/backup/AAAA-MM-DD_HHMMSS
```

Validar:

- [ ] Sistema sobe após restauração.
- [ ] Usuários restaurados conseguem login.
- [ ] Histórico aparece.
- [ ] Evidências anexadas aparecem.
- [ ] CSV exporta dados restaurados.
- [ ] Dashboard bate com dados esperados.

## 19. Validação final antes de liberar uso

Liberar uso somente se todos estes itens estiverem OK:

- [ ] Administradores testados.
- [ ] Usuários nominais testados.
- [ ] Senha forte validada.
- [ ] Senha temporária gerada automaticamente testada.
- [ ] Auditoria administrativa testada.
- [ ] Upload de PDF testado.
- [ ] Upload de imagem testado.
- [ ] Acesso a evidências protegido.
- [ ] Histórico e CSV testados.
- [ ] Backup manual testado.
- [ ] Agendador de backup configurado.
- [ ] Restauração testada.
- [ ] Firewall/rede interna revisados.
- [ ] `.env` não foi enviado ao GitHub.
- [ ] Credenciais iniciais foram trocadas.

## 20. Registro da homologação

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

