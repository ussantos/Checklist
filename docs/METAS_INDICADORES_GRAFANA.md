# Metas, Indicadores e Grafana

## Decisão de modelagem

Metas e indicadores foram consolidados em uma única entidade: `MetricType`.

Motivo: no Checklist, a meta é uma regra de leitura do indicador, não um objeto operacional separado. O indicador define nome, área, frequência, unidade, fórmula, fonte de dados, meta/alvo e vínculo com cargo ou atividade. Os valores realizados continuam em `MetricRecord`, preservando o histórico numérico para dashboards internos e Grafana.

## Regra operacional

Nenhum dashboard ou painel de indicador deve ser criado manualmente no Grafana.

O Checklist sincroniza o Grafana via API quando um administrador:

- cria uma meta/indicador;
- altera nome, fórmula, fonte, meta, frequência, unidade ou visualização;
- ativa ou desativa uma meta/indicador;
- exclui uma meta/indicador;
- importa metas/indicadores por XLSX;
- clica em sincronização manual na tela administrativa.

Cada área vira um dashboard do Grafana com UID determinístico `checklist-metricas-<area>`. A sincronização usa `overwrite=true`, portanto é idempotente: rodar novamente atualiza o dashboard existente em vez de duplicar painéis.

## Regras automáticas de visualização

As regras ficam em `checklists/grafana_sync.py` e devem continuar programáticas:

- visualização manual diferente de `Automático` sempre vence;
- indicadores percentuais com meta numérica usam medidor;
- metas de tempo ou regra "menor ou igual" usam número em destaque;
- séries diárias, semanais, mensais e anuais usam série temporal por padrão;
- indicadores sem histórico suficiente usam número em destaque;
- indicadores inativos deixam de aparecer no dashboard automático.

## Importação XLSX

A planilha esperada contém:

- `Etapa`
- `Descrição`
- `Indicador Principal`
- `Meta`
- `Entregáveis`
- `Pontos de Atenção`

O importador cria ou atualiza indicadores vinculados ao cargo `Atendente Comercial`, infere frequência, unidade e direção da meta e sincroniza o Grafana ao final.

Comando:

```powershell
docker compose exec web python manage.py import_metrics_xlsx /tmp/metas_indicadores.xlsx
```

Também é possível importar pela tela **Acompanhamento > Indicadores** ou **Acompanhamento > Metas**.

## Falhas de sincronização

Se o Grafana estiver indisponível, o CRUD do Checklist permanece salvo e o indicador recebe status `Falhou`, com o erro em `grafana_last_error`. O administrador pode clicar em **Sincronizar Grafana** depois que o serviço voltar.
