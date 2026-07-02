# Dashboards Grafana — Checklist

O Grafana é iniciado pelo Docker Compose para uso administrativo/local. O datasource PostgreSQL é provisionado em `grafana/provisioning/datasources/checklist-postgres.yml`.

## Segurança e permissões

O Grafana não conhece as permissões do Django. Portanto:

- não habilite acesso anônimo;
- mantenha `GRAFANA_BIND=127.0.0.1:3000` sempre que possível;
- exponha apenas via VPN/rede interna quando necessário;
- considere as contas do Grafana como contas administrativas;
- usuários comuns devem usar as telas internas do Checklist.

## Criação dos dashboards

Dashboards de metas e indicadores não são mais editados manualmente nem mantidos como JSON estático por um operador.

O Checklist gera dashboards automaticamente via API do Grafana quando o administrador altera o módulo **Metas e Indicadores**:

- criação;
- edição;
- ativação;
- desativação;
- exclusão;
- importação XLSX;
- sincronização manual.

Cada área de indicador gera um dashboard com UID determinístico `checklist-metricas-<area>`. A chamada usa `overwrite=true`, então a sincronização é idempotente e não duplica painéis.

## Regras de visualização

As regras programáticas estão documentadas em `docs/METAS_INDICADORES_GRAFANA.md` e implementadas em `checklists/grafana_sync.py`.

Resumo:

- percentuais com meta numérica usam medidor;
- tempo ou regra "menor ou igual" usa número em destaque;
- séries diárias, semanais, mensais e anuais usam série temporal;
- indicadores inativos saem do dashboard automático;
- falhas ficam registradas no próprio indicador para ressincronização posterior.
