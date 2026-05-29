# Spec - Polymarket Tmax Forecaster (NZWN)

> **Spec version:** 1.0
> **Idioma:** PT-BR (ASCII em CLIs/logs/paths)
> **Status:** v1 do spec; pre-implementacao (Fase 0 do plano).

Este diretorio contem os quatro artefatos que governam a construcao do **Polymarket Tmax Forecaster** para a estacao **NZWN (Wellington)**: previsao intraday do Tmax inteiro em °C com forecast por checkpoint (CP), confianca calibrada, modulo de late spike e auditoria forense anti-nowcaster.

Os artefatos foram derivados de `references/legacy/Polymarket Tmax Forecaster - Design & Specs (v1) c38caff902d1420bbdf62c6c7ccd5f01.md` e da auditoria do dataset historico `NZWN.csv` (112.190 linhas, IEM ASOS, 2020-01-01 a 2026-05-27, cadencia 30 min).

---

## Indice

| Arquivo | Conteudo | Quando ler |
|---------|----------|------------|
| `requirements.md` | Requisitos formais EARS (`REQ-*`), contratos, gates, pendencias (`OPN-*`). | **Sempre primeiro.** Qualquer mudanca de codigo deve referenciar um `REQ-*`. |
| `design.md` | Arquitetura, modulos, schemas de dados, stack, fluxos CP-aware, decisoes congeladas. | Antes de comecar uma fase para entender **como** implementar. |
| `implementation-plan.md` | Fases 0-8 com entregaveis, gates de saida, kill criteria e cronograma. | No inicio de cada fase para saber o que produzir e quando parar. |
| `tasks.md` | Backlog acionavel (`T-FASE-N`) com checkboxes, criterios de done e mapa REQ -> tasks. | Diariamente. Marcar `[x]` ao concluir; abrir issues para tasks novas referenciando o REQ que justifica. |

---

## Como usar

### 1. Antes de codar
- Leia `requirements.md` integralmente.
- Confirme que o REQ que voce vai cumprir esta versionado.
- Verifique a fase atual em `tasks.md`. Tasks de fases futuras estao bloqueadas.

### 2. Durante a implementacao
- Cada PR deve referenciar pelo menos um `REQ-*` e uma task `T-*`.
- Mudanca em qualquer arquivo de `contracts/` exige bump de versao no proprio contrato e re-execucao das auditorias relevantes.
- Reverse-import guard (REQ-AUD-3) e ASCII guard (REQ-OPS-2) sao validados em CI; nao desabilitar.
- Cada fase tem **gates pre-registrados**. Eles falham builds. Nao "tunar" thresholds para passar.

### 3. Ao avancar de fase
- Verificar em `implementation-plan.md`:
  - todos entregaveis prontos,
  - gate de saida atendido,
  - kill criteria nao acionados,
  - relatorio publicado em `reports/`.
- Verificar em `tasks.md` que todas as tasks da fase atual estao `[x]`.
- Rodar `tmax audit --phase all` e validar `audits/<run_id>/h0_verdict.json` (`H0_rejected: true` e `gate_violations: []`).

### 4. Em caso de kill criterion
- **Parar a fase.** Nao avancar.
- Escrever `reports/<phase>_postmortem.md` com hipotese de causa.
- Se necessario, abrir issues atualizando requirements (com bump de versao e justificativa).

---

## Estado atual do projeto

- **Codigo:** ainda nao escrito (greenfield).
- **Dados:** `NZWN.csv` (raiz do repo, 20 MB) - IEM ASOS, deve virar `references/legacy/datasets/NZWN.csv` na Fase 0 e ser substituido por snapshots versionados (REQ-DAT-1).
- **Documento v1:** `Polymarket Tmax Forecaster - Design & Specs (v1) c38caff902d1420bbdf62c6c7ccd5f01.md` na raiz - deve ir para `references/legacy/` na Fase 0.

### Versoes de contratos congeladas

- `Q_VERSION = 1.0` — funcao de quantizacao oficial: `Q(x) = floor(x + 0.5)`, `B(k) = [k - 0.5, k + 0.5)` (REQ-CON-1, `contracts/quantization.md`).
- `EXECUTION_VERSION` — congelar como `1.0` na T-8-0 (REQ-MET-5, `contracts/execution.md`); requerido **antes** da Fase 8.
- `MODEL_VERSION` — bumpar a cada mudanca em `tau` (Fase 3+), `safety_margin` NWP (4.5.2), regimes GMM (secao 7) ou pipeline de features.
- `criterion_version` (em `audits/run_h0_audit.py`) — bumpar quando os gates da REQ-AUD-2 mudarem.

### Regra dura: contrato muda -> auditoria re-roda

Qualquer alteracao em `contracts/*.md` ou em qualquer `*_VERSION` exige:

1. bump explicito da versao no proprio contrato (commit do diff = commit do bump),
2. atualizacao de `criterion_version` se a alteracao afetar os gates,
3. **re-execucao completa** do protocolo H0 (`tmax audit --phase all`),
4. publicacao de novo `audits/<run_id>/h0_verdict.json`,
5. relatorio comparativo em `reports/contract_change/<from>_to_<to>.md`.

Sem essas 5 etapas, a mudanca de contrato e considerada **invalida** e o CI rejeita o merge.

### Como rodar (apos Fase 0 concluida)

> Comandos validos a partir do final de Fase 0/inicio de Fase 1. Antes disso, so `pip install -e .` esta disponivel.

```powershell
# 1) instalar (Windows)
py -3 -m pip install -e .

# 2) gerar snapshots brutos a partir do CSV historico (Fase 1)
py -3 -m core.cli ingest-history --csv .\NZWN.csv --station NZWN

# 3) construir features para um dia/CP especificos
py -3 -m core.cli build-features --station NZWN --date 2026-05-20 --cp 23

# 4) emitir forecast (baselines em Fase 2; ML em Fase 3+)
py -3 -m core.cli forecast --station NZWN --date 2026-05-20 --cp 23

# 5) postmortem D+1
py -3 -m core.cli postmortem --station NZWN --date 2026-05-20

# 6) auditoria forense completa
py -3 -m core.cli audit --phase all
```

**Onde colocar `NZWN.csv`:** raiz do repo (default) ou path passado via `--csv`. Apos a Fase 1, snapshots versionados em `artifacts/raw/metar/NZWN/<yyyy>/<mm>/<dd>.csv` substituem o uso direto do CSV.

**Onde os outputs caem:**
- `artifacts/forecasts/<run_id>.parquet`
- `artifacts/logs/<run_id>.jsonl`
- `reports/postmortem/<date_local>.md`
- `audits/<run_id>/h0_verdict.json`

> Todos os paths sao **ASCII-only**; CIs rejeitam unicode (REQ-OPS-2).

### Decisoes ja congeladas

- `Q(x) = floor(x + 0.5)`, `B(k) = [k - 0.5, k + 0.5)` (default).
- **CP_SET oficial:** `[20:00, 21:00, 22:00, 23:00] UTC` (REQ-CON-6); CP operacional = `23:00 UTC` (~11:00 local Pacific/Auckland).
- **`day_complete`:** `n_obs >= 40 AND max_gap <= 120 min AND 1 obs em cada quartil do dia local` (REQ-CON-7).
- **Fallback policy:** `imputed` apenas se `metar` ausente/ilegivel; kill criterion `> 0.5%` (REQ-CON-8).
- **Verdade observacional (`T_obs_int`):** inteiro extraido do `metar` cru (4.1.1, REQ-CON-3).
- **Late spike label:** `late_spike_l1 = (k_eod != k_cp)` (4.4 + 9; sobre inteiros).
- **`prob_dist` baselines:** empirica condicional `(month, cp, k_cp)` com Laplace; **proibido** gaussiana ingenua em `core/`.
- **`prob_dist` ML:** softmax band-aware com `tau` congelado em `nzwn/config/model.yaml` (default `tau=0.5, mode=linear`).
- **Suporte K:** derivado de climo+NWP percentis +/- 2, truncado a `[-10, 40]` °C (4.5.1).
- **NWP selection v1:** latest run `<= cp - 30min`; valid_time anchor = hora climatologica do Tmax (4.5.2).
- **Shadow execution:** `taker_at_quote`, `fee=200 bps`, `sizing=1 unit`, `fill=assume_full_fill` (REQ-MET-5; congelar em T-8-0 antes da Fase 8).
- **Tuning protocol:** nested walk-forward; tunar **apenas** thresholds operacionais (REQ-MET-6).
- Stack: Python 3.11, polars, scikit-learn, lightgbm, conformal por CP.

### Decisoes em aberto (bloqueiam fases)

| ID | O que decidir | Bloqueia | Quem |
|----|---------------|----------|------|
| OPN-1a | Validacao **minima** do resolver: estacao + tz + janela do dia | Fase 1 | T-0-7 |
| OPN-5 | Fonte NWP (ECMWF / GFS / blending) e cobertura historica | Fase 4 | T-4-1 |
| OPN-1 | Validacao binaria de Q vs Polymarket (auditoria 30+ dias) | Fase 8 | T-8-1 |
| OPN-3 | Cutoffs operacionais "NO caro" / `min_edge_*` / `min_confidence` | Fase 8 | aprender via REQ-DEC-3 + REQ-MET-6 (T-8-4) |

---

## Convencoes

- Todos os logs, JSONLs, paths e CLIs sao **ASCII-only** (REQ-OPS-2).
- Comandos documentados usam `py -3` como invocacao primaria (Windows-friendly).
- Timestamps internos sempre em UTC; conversoes via `zoneinfo.ZoneInfo("Pacific/Auckland")`.
- Hashes SHA256 para snapshots, modelos, datasets.
- Seeds fixas (`random=42`, `numpy=42`, `lightgbm.seed=42` etc.) para determinismo verificavel em CI.

---

## Como contribuir mudancas no spec

1. Abrir branch `spec/<area>-<descricao>`.
2. Editar o(s) artefato(s) afetado(s) e registrar o motivo no commit.
3. Se a mudanca afeta `contracts/`, bumpar a versao do contrato e atualizar `criterion_version` em `audits/run_h0_audit.py`.
4. Atualizar a tabela de rastreabilidade em `tasks.md` se um novo `REQ-*` for criado.
5. PR review por pelo menos um revisor com contexto sobre auditoria forense.

---

## Glossario rapido

- **CP:** checkpoint (instante UTC em que uma previsao e emitida).
- **Tmax(D0):** Tmax inteiro publicado pelo METAR no dia local D0.
- **Q(x), B(k):** funcao de quantizacao e banda inversa - default congelado.
- **NWP:** numerical weather prediction (forecast historico, **nao** archive).
- **Late spike:** revisao tardia do Tmax apos o CP que cruza para outro inteiro/bracket.
- **EV:** expected value realizado em shadow trading (metrica primaria do produto).
- **Verdict file:** `audits/<run_id>/h0_verdict.json` - obrigatorio em toda execucao de auditoria.

Para o glossario completo, ver `requirements.md` secao 0.

---

## Referencias

- v1 (historico): `references/legacy/polymarket-tmax-forecaster-v1.md`.
- Atribuicao da fonte de dados: Iowa Environmental Mesonet (IEM ASOS).
- Termos de uso e citacao: `references/legacy/data_sources.md` (a ser criado em T-0-1).
