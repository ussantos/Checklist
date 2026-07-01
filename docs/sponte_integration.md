# Integração Sponte

Este documento descreve os cuidados técnicos e operacionais da integração entre o Checklist e as APIs da Sponte.

## Objetivo

A API consta no contrato como cortesia, mas o Checklist deve usá-la com segurança, cache local, limite defensivo de chamadas e logs sem dados sensíveis.

## Variáveis de ambiente

Configure apenas no `.env` do servidor. Nunca commite segredos.

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

`SPONTE_API_ENABLED=False` mantém o sistema funcionando sem chamadas externas. Para ativar, configure `True` e preencha `SPONTE_API_CLIENT_CODE` e `SPONTE_API_TOKEN`.

As variáveis antigas `SPONTE_API_URL`, `SPONTE_CODIGO_CLIENTE`, `SPONTE_TOKEN` e `SPONTE_TIMEOUT_SECONDS` ainda são aceitas por compatibilidade, mas novas instalações devem usar os nomes `SPONTE_API_*`.

Sincronizações datadas do Sponte devem sempre considerar o dia da execução para frente. `SPONTE_SCHEDULE_SYNC_DAYS_AHEAD` define a quantidade de dias futuros buscados. `SPONTE_SCHEDULE_SYNC_DAYS_BACK` é mantida apenas por compatibilidade e deve permanecer `0`; dados antigos não são importados nem usados para bloquear horários.

## Situação da Aula

A integração do Checklist deve permanecer na superfície SOAP da Sponte. A agenda regular é lida por `GetAgendaAluno` e, quando disponível, a situação da aula é complementada por consultas SOAP de diário de aula livre.

Como a API SOAP nem sempre devolve a **Situação da Aula** na agenda, a fonte operacional para auditoria e correção em lote é o relatório Sponte **Aulas Livres** exportado em XML pela própria interface do Sponte. Gere o relatório com:

- **Situação da Aula** = Todas;
- período completo a reconciliar;
- tipo de relatório detalhado;
- exportação em XML.

O XML usa códigos de situação mapeados para as nomenclaturas do Sponte:

- `0`: `Não dada`;
- `1`: `Presença`;
- `2`: `Falta`;
- `3`: `Cancelada`.

Para auditar aulas já importadas usando o XML do relatório, sem alterar o banco:

```bash
docker compose exec web python manage.py reconcile_sponte_lessons --start-date 2025-11-01 --end-date 2026-06-30 --report-xml /app/tmp/aulas-livres.xml --audit-only
```

Para aplicar a correção:

```bash
docker compose exec web python manage.py reconcile_sponte_lessons --start-date 2025-11-01 --end-date 2026-06-30 --report-xml /app/tmp/aulas-livres.xml
```

Também é possível aplicar a correção pela tela **Gestão Pedagógica > Agenda de Aulas** ou pela **Agenda do Instrutor**, no bloco **Corrigir situações pelo XML do Sponte**. Informe o período do relatório, envie o XML exportado e confirme a importação.

O comando e a tela usam o XML como fonte de verdade para o período informado. Aulas que existem no banco, mas não aparecem no relatório daquele aluno/período, são removidas ou canceladas conforme a regra de preservação local. O modo `--audit-only` calcula o mesmo impacto dentro de uma transação com rollback.

## Dados vindos da Sponte

O Checklist trata a Sponte como fonte principal para:

- alunos;
- responsáveis;
- cursos;
- matrículas;
- agenda regular de Aulas Livres.

A agenda operacional de aulas experimentais ou Play, regras de kits, ocupação de sala e alerta de assistente continuam sendo regras locais do Checklist.

## Dados mantidos localmente

O Checklist persiste apenas o necessário para operação:

- IDs externos;
- nomes;
- matrícula;
- contato básico;
- status;
- curso;
- sala;
- datas/horários de aulas sincronizadas.

Cursos vindos da Sponte preservam campos locais de planejamento, como valor, quantidade de kits e máximo por horário.

## Campos descartados por segurança

Normalizadores da integração descartam campos cujo nome indique dado sensível, como:

- CPF;
- RG;
- documento;
- login;
- senha;
- token;
- chave.

Esses campos não devem ser persistidos no Checklist nem aparecer em logs.

## Cache e contingência

As chamadas SOAP passam por `checklists.sponte_client.SponteSOAPClient`.

O endpoint `GetSalas` exige o payload completo definido no WSDL (`nSalaID`, `sSigla`, `sDescricao`, `nAtivo` e `sParametrosBusca`), mesmo quando os filtros ficam vazios. Não use somente `sParametrosBusca` nessa chamada.

O cache é feito por tipo de consulta e parâmetros. O TTL é controlado por `SPONTE_API_CACHE_TTL_MINUTES`.

Se houver timeout ou erro de rede, o cliente tenta usar o último cache válido quando existir. Se não houver cache, retorna erro amigável para a tela administrativa.

As telas não fazem chamadas externas dentro de templates. As sincronizações disparadas por botões são registradas como jobs em segundo plano; o usuário recebe notificação de início, conclusão ou falha enquanto continua usando o sistema.

## Rate limit local

`SPONTE_API_MAX_REQUESTS_PER_MINUTE` limita chamadas externas por minuto. Esse controle é defensivo, mesmo sem cobrança explícita por request no contrato.

Com `SPONTE_API_WAIT_ON_RATE_LIMIT=True`, o cliente aguarda a próxima janela de minuto quando o limite local é atingido, registra `rate_limit_wait` no log técnico e continua a sincronização. `SPONTE_API_RATE_LIMIT_WAIT_PADDING_SECONDS` adiciona uma pequena folga após a virada do minuto para evitar bater no limite por diferença de relógio.

Valores recomendados:

- homologação: `10`;
- produção pequena: `30`;
- integração intensiva: manter `30`, rodar em segundo plano e avaliar caso a caso antes de aumentar.

## Logs seguros

Os logs da integração registram apenas:

- método SOAP chamado;
- status técnico (`success`, `cache_hit`, `timeout`, `network_error`, `rate_limit`, etc.);
- duração;
- quantidade aproximada de registros;
- código de retorno Sponte quando existir.

Nunca registrar:

- token;
- código do cliente;
- payload SOAP completo;
- resposta completa;
- CPF/RG;
- login/senha de portal;
- dados pessoais sensíveis.

## Como testar sem chamar a API real

Use testes unitários com `SponteSOAPClient(fetcher=...)` para simular respostas XML.

Comandos úteis:

```bash
docker compose exec web python manage.py test checklists.tests.SponteSOAPClientSafetyTests
docker compose exec web python manage.py test checklists.tests.SponteCourseImportTests
```

## Operação

Para sincronizar dados manualmente:

- alunos: **Gestão Pedagógica > Alunos > Importar do Sponte**;
- cursos: **Gestão Pedagógica > Cursos > Sincronizar Sponte**;
- agenda regular: **Gestão Pedagógica > Agenda de Aulas > Sincronizar Sponte**.

Ao clicar, o job entra na fila e a tela retorna imediatamente. A notificação final indica sucesso ou falha. Se a mesma pessoa clicar de novo enquanto já existe job equivalente em andamento, o sistema reutiliza o job existente em vez de criar concorrência desnecessária.

Use VPN/firewall. A aplicação e a API de backup não devem ser expostas publicamente.
