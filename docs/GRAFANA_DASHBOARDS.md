# Dashboards Grafana — Checklist

O Grafana é provisionado automaticamente pelo Docker Compose para uso administrativo/local.

## Segurança e permissões

O Grafana não conhece as permissões do Django. Portanto:

- não habilite acesso anônimo;
- mantenha `GRAFANA_BIND=127.0.0.1:3000` sempre que possível;
- exponha apenas via VPN/rede interna quando necessário;
- considere as contas do Grafana como contas administrativas;
- usuários comuns devem usar o dashboard interno do Django em `/metricas/`.

Essa decisão evita vazamento de indicadores entre cargos/usuários enquanto não existir um proxy/embed protegido pelo Django.

## Provisionamento

- Datasource: `grafana/provisioning/datasources/checklist-postgres.yml`
- Provider de dashboards: `grafana/provisioning/dashboards/checklist-dashboards.yml`
- Dashboards versionados: `grafana/dashboards/*.json`

## Dashboards

Os dashboards provisionados são:

- diário;
- semanal;
- mensal;
- anual.

Todos consultam o PostgreSQL real da aplicação via datasource `Checklist PostgreSQL`.

## Filtros

Cada dashboard possui variáveis:

- `Tipo/cargo`;
- `Usuário`.

O filtro de usuário é apenas operacional para administradores. Ele não deve ser entendido como controle de segurança para usuário comum.

## Consultas

As queries ficam versionadas nos JSONs dos dashboards em `targets[].rawSql`, usando CTEs legíveis para:

- definir o período pelo time picker do Grafana;
- listar indicadores ativos por cargo;
- calcular meta proporcional conforme frequência do indicador;
- somar realizado por indicador;
- detalhar realizado por usuário;
- gerar totalizadores por cargo e total geral.
