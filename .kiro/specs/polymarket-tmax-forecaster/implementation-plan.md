# Implementation Plan - Polymarket Tmax Forecaster (NZWN)

> **Spec version:** 1.0
> **Idioma:** PT-BR (ASCII em CLIs/logs/paths)
> **Companion:** ver `requirements.md`, `design.md`, `tasks.md`

Este plano transforma o design em um caminho **incremental, com gates pre-registrados e kill criteria explicitos**. Nada avanca para a fase seguinte sem evidencia fora-da-amostra (REQ-MET-3, REQ-MET-4) e sem passar nos gates anti-nowcaster (REQ-AUD-2).

---

## Resumo executivo

| Fase | Nome | Objetivo principal | Duracao sugerida |
|------|------|--------------------|------------------|
| 0 | Setup e contratos | repo, CI, contratos congelados | 2-3 dias |
| 1 | Data contracts + labels + EDA | dataset CP-aware reproduzivel | 1 semana |
| 2 | Baselines + harness de auditoria | persistencia/climatologia + protocolo H0 rodando | 1-2 semanas |
| 2b | TAF como alerta (opcional) | TAF feeds em confidence (nao no core) | +1 semana se houver fonte |
| 3 | Ridge band-aware (primeiro ML) | bater baselines em >= 2/3 splits | 1-2 semanas |
| 4 | NWP residual + disagreement | core de producao | 2-3 semanas |
| 5 | Calibracao + confidence audit | IC80 calibrado + ECE <= 0.05 | 1-2 semanas |
| 6 | AR online (opcional) | reduzir bias/drift sem leakage | 1-2 semanas |
| 7 | Late spike como alerta | spike_risk calibrado | 1-2 semanas |
| 8 | Shadow trading + EV | metrica primaria realizada | 2-4 semanas |

Tempo total realista (1 dev focado, sem multi-cidade): **3-4 meses** para chegar a Fase 8 com uma metrica primaria realista.

---

## Regras globais (valem em todas as fases)

Conforme REQ-* relevantes:

1. **Splits:** expanding-window com >= 3 splits + segmentacao por dificuldade (regime, mes, lead) (REQ-MET-3).
2. **Baselines obrigatorios:** persistencia, climatologia smoothed; NWP cru quando aplicavel.
3. **Auditoria forense roda em toda fase** com baselines e variantes (REQ-AUD-1).
4. **Promocao:** ganho em >= 2/3 splits + sem regredir gates (REQ-AUD-2, REQ-MET-4).
5. **Determinismo:** seeds fixas, CI valida SHA256 igual em treinos consecutivos (REQ-MOD-6).
6. **ASCII e exit codes honestos.** Soft-fail e bug, nao feature (REQ-OPS-1, REQ-OPS-2).
7. **Hashes (SHA256)** em snapshots, modelos e dataset_version (REQ-DAT-1, REQ-DAT-5).
8. **Reverse-import guard ativo desde Fase 0.** (REQ-AUD-3)

---

## Fase 0 - Setup e contratos congelados

**Objetivo:** estabelecer o esqueleto do repo e os contratos que tudo depois respeita.

**Entregaveis:**
- Estrutura de diretorios (REQ-REP-1) criada e documentada.
- `pyproject.toml` com Python 3.11; deps pinadas (REQ-SEC-2): `polars`, `numpy`, `scikit-learn`, `lightgbm`, `pyarrow`, `typer`, `structlog`, `httpx`, `pytest`, `ruff`, `mypy`.
- `contracts/quantization.md` (REQ-CON-1) com `Q_VERSION=1.0` e exemplos.
- `contracts/imputation.md` (REQ-DAT-3) com regra explicita por feature.
- `contracts/objective.md` (REQ-DEC-3) com a funcao-objetivo escolhida (default proposto: `max(EV) sujeito a max_drawdown <= 5%`).
- `contracts/features.md` skeleton.
- `references/legacy/` com o markdown v1 + `data_sources.md` (REQ-SEC-3).
- `nzwn/config/station.yaml`: `icao: NZWN`, `lat`, `lon`, `tz: Pacific/Auckland`, `cp_operacional_utc: 23:00`.
- CI baseline (`.github/workflows/ci.yml`): lint, mypy, pytest, reverse-import guard, ASCII guard.
- `tests/conftest.py` com seeds fixas + golden test placeholder.

**Gate de saida:**
- CI verde no commit inicial.
- Reverse-import guard testado: import proibido falha o build (caso negativo testado).
- ASCII guard testado: arquivo com unicode em path quebra a build (caso negativo testado).

**Kill criteria:** nenhum (fase de setup).

**Mapeamento de requirements:** REQ-REP-1, REQ-REP-3, REQ-REP-4, REQ-AUD-3, REQ-OPS-2, REQ-CON-1, REQ-DAT-3, REQ-DEC-3, REQ-SEC-2, REQ-SEC-3.

---

## Fase 1 - Data contracts + labels + EDA basica

**Objetivo:** transformar `NZWN.csv` em dataset CP-aware reproduzivel com labels corretos.

**Entregaveis:**
- `core/ingest/iem_csv.py`: parser de `NZWN.csv` -> tabela `metar_observations` (ver design 4.3).
- `core/ingest/snapshot.py`: snapshot deterministico (REQ-DAT-1) - particiona o CSV por dia local em `artifacts/raw/metar/NZWN/yyyy/mm/dd.csv` + `manifest.jsonl` com SHA256.
- `core/io/timeutil.py`: `day_local_window`, `to_utc`, `to_local`. Testes DST (REQ-CON-4).
- `core/labels/tmax.py`: gera `tmax_labels` cobrindo 24h locais; usa **inteiro do `metar` cru** (REQ-CON-3) com fallback documentado para `tmpf` quando regex falhar (`data_quality=imputed`).
- `core/features/builder.py`: dataset_builder CP-aware com checagem `feature_max_ts <= cp_utc` (REQ-CON-5, REQ-AUD-4).
- `core/baselines/persistence.py`, `core/baselines/climatology.py`: persistencia e climatologia smoothed (calculada sobre o train split com janela >= 12 meses).
- EDA inicial em `reports/eda/`:
  - distribuicao de hora local do Tmax por mes,
  - taxa de "early peak" e "Tmax fora do horario tipico" (REQ - secao 11.3 v1),
  - NaN/missing por coluna,
  - cobertura: dias com `day_complete=True` vs incompletos.
- Testes unitarios: timezone, DST (2 transicoes/ano), janela 24h, causalidade `< CP`.
- 2-3 golden tests (dias fixos -> outputs esperados em parquet hashed).

**Gate de saida:**
- Frozen observation test passa para baselines: nenhuma feature usa `> cp_utc`.
- Reprodutibilidade: rodar duas vezes -> mesmo SHA256 do `features_per_cp` para um conjunto de dias congelados.
- `day_complete` calculado conforme REQ-CON-7 e taxa de `False` reportada por mes em `reports/eda/coverage.md`.
- Discrepancia entre `Q(round((tmpf-32)*5/9))` e `T_obs_int` extraido do `metar` documentada em `reports/eda/decimal_vs_int_check.md`.
- Taxa de fallback (`data_quality.tmp_c_int = "imputed"`, REQ-CON-8) reportada por mes.

**Kill criteria (hard):**
- Se `discrepancia_global > 0.5%` (decimal vs int do metar), **parar** - o label/truth nao esta confiavel; **nao** avancar para Fase 2 antes de corrigir o parser ou trocar a fonte.
- Se `fallback_rate_global > 0.5%` (REQ-CON-8), idem.
- Se `taxa global de day_complete=False > 5%`, parar e revisar parser/janela antes de seguir.

**Mapeamento de requirements:** REQ-CON-3, REQ-CON-4, REQ-CON-5, REQ-CON-6, REQ-CON-7, REQ-CON-8, REQ-DAT-1, REQ-DAT-2, REQ-DAT-3, REQ-AUD-4, REQ-REP-2.

---

## Fase 2 - Baselines reproduziveis + harness de auditoria

**Objetivo:** rodar baselines fim-a-fim e ter o protocolo H0 emitindo `h0_verdict.json` para baselines.

**Entregaveis:**
- CLI minimo (`tmax forecast`, `tmax postmortem`) para baselines (REQ-OPS-1).
- `core/cli/forecast.py`: emite `forecasts.parquet` com `prob_dist` **empirica condicional** (design 8, contrato de baselines):
  - distribuicao discreta `P(k_eod = k | month, cp, k_cp)` calculada **somente sobre o train split** com suavizacao de Laplace (`alpha=1`),
  - fallback para bucket marginal `(month, cp)` quando `n < 30` no bucket condicional (logado como `data_quality.prob_dist = "fallback_marginal"`),
  - truncamento ao `support_K` (design 4.5.1).
- **Proibido** em Fase 2 do core: `prob_dist` parametrico Gaussiano sobre `mu = climo, sigma = MAE` ou similar (vai para `experiments/` como ablation rotulada).
- `core/cli/postmortem.py`: D+1 com truth vs forecast (REQ-OPS-4).
- `audits/run_h0_audit.py` rodando as 7 fases sobre baselines:
  - lead-time, frozen obs, counterfactual same-temp, no-temperature, horizon, extreme spike, economic_edge=skipped (Fase 8 ainda nao ativa).
- Output obrigatorio: `audits/<run_id>/h0_verdict.json` (REQ-AUD-1).
- Logs JSONL completos (REQ-OPS-3).
- Tabela `bracket_match @ coverage in {25%, 50%, 75%, 100%}` em `reports/baselines.md` (REQ-MET-2).

**Gate de saida:**
- Auditoria roda em baselines e produz verdict file - sem soft-fail.
- Persistencia bate climatologia em CPs proximos do meio do dia, **e** climatologia bate persistencia em CPs early; isto serve como "calibracao do ferramental" (sanity).

**Kill criteria:** se persistencia nao bate trivialmente em 1h, parser de `tmax_labels` esta errado - voltar para Fase 1.

**Mapeamento de requirements:** REQ-OPS-1, REQ-OPS-3, REQ-OPS-4, REQ-AUD-1, REQ-MET-2, REQ-MET-3.

---

## Fase 2b - TAF como alerta (opcional)

**Objetivo:** Se feed TAF estiver disponivel, integrar como sinal exogeno no `confidence_score` (nao no core).

**Entregaveis:**
- `core/ingest/taf.py`: snapshot bruto + SHA256 (REQ-DAT-4).
- `core/ingest/taf_parser.py`: segmentacao em `(issued_time_utc, valid_from, valid_to)`.
- Features de transicao (rain/clearing/thunder/wind shift) consumidas pelo confidence_score.
- Auditoria de timestamps: nenhum TAF emitido apos o CP entra nas features (REQ-DAT-4).

**Gate de saida:**
- Test de causalidade do TAF passa (rejeita TAF emitido apos o CP em backtest).
- Adicao do TAF ao confidence_score nao degrada coverage nem ECE (auditado em hold-out).

**Kill criteria:** se auditoria de causalidade falha mesmo apos correcao, manter TAF apenas como alerta visual em postmortem; nao usar como feature.

**Mapeamento de requirements:** REQ-DAT-4, REQ-CONF-2.

---

## Fase 3 - Ridge band-aware (primeiro ML)

**Objetivo:** primeiro modelo aprendido que **bate** as baselines em >= 2/3 splits sem violar gates.

**Entregaveis:**
- `core/models/ridge_band.py`: Ridge convencional fitado em `delta_vs_climo` (`y = T_obs_dec - climo`). Saida bruta = `T_latent_dec` (decimal). Usar band-aware loss **apenas** como criterio de scoring para selecao de hiperparametros (`alpha` do Ridge). **Sem** "projecao de gradient" inventada.
- `core/models/prob_from_latent.py`: implementar `latent_to_prob_dist` (design 8.1.1) com:
  - `support_K` derivado por `support_K(...)` (design 4.5.1),
  - `tau` fixado em `nzwn/config/model.yaml` (default v1: `tau=0.5`, `mode=linear`),
  - `tau` versionado e **proibido** de ser ajustado durante tuning de threshold (REQ-MET-6).
- `p50_int = Q(T_latent_dec)`. IC80 derivado posteriormente em Fase 5 via conformal (Fase 3 pode reportar IC empirico ingenuo `[p50-1, p50+1]` apenas como sanity).
- Walk-forward expanding-window (>= 3 splits) com IC bootstrap (>= 1000 reamostragens) (REQ-MET-3).
- Gates pre-registrados (REQ-AUD-2) implementados como checks que falham o build:
  - SS(1h) > 0.08 IC95% excluindo 0,
  - SS(3h) > 0.10,
  - corr(y_hat, truth) - corr(y_hat, T_now) >= 0.20,
  - I_T_obs < 0.10 (permutation importance da observacao corrente),
  - AUC contrafactual same-temp > 0.70.
- Counterfactual same-temp e no-temperature variant rodando.
- Relatorio comparativo: persistencia vs climatologia (`prob_dist` empirico) vs Ridge band-aware (`prob_dist` softmax band-aware).

**Gate de saida (REQ-MET-4 - kill criterion):**
- Ridge band-aware **deve** bater `max(persistence, climatology)` em bracket-match no CP operacional em pelo menos 2/3 splits, com IC bootstrap excluindo zero.
- Gates anti-nowcaster (REQ-AUD-2) passam.

**Kill criteria:** se Ridge nao bate baselines, **PARAR**. Nao avancar para Fase 4. Revisitar:
- features (talvez climatology esta errada, falta normalizacao por mes),
- labels (Tmax mal computado em DST?),
- janela (`closed='left'` correto em todos os rolls?).
Documentar em `reports/phase3_postmortem.md` antes de tentar de novo.

**Mapeamento de requirements:** REQ-MOD-1, REQ-MOD-2, REQ-MOD-6, REQ-AUD-2, REQ-MET-3, REQ-MET-4.

---

## Fase 4 - NWP residual learning + disagreement

**Objetivo:** core de producao com NWP como baseline e ML aprendendo o erro/bias.

**Pre-requisito:** OPN-5 fechado (escolha de fonte NWP).

**Entregaveis:**
- `core/ingest/nwp.py`: ingestor de NWP forecast historico (NAO archive) (REQ-DAT-5). Snapshots por `(model, run_time_utc, lead_h, valid_time_utc)`.
- `core/features/nwp.py`: features de spread, disagreement, king-conflict.
- `core/models/residual_lgbm.py`: LightGBM treinando residual `(truth - NWP_baseline)` condicionado por mes/CP/regime/spread + features intraday.
- Ablations:
  - NWP cru,
  - NWP + residual sem features intraday,
  - NWP + residual completo,
  - Ridge band-aware (Fase 3) como referencia.
- Variant "no-temperature" do modelo Fase 4 (sem `tmpf`/`t_so_far_max_c_int`/`Tmax(D-1)`) - REQ secao 18 v1.

**Gate de saida:**
- Bracket-match no CP operacional melhora vs Ridge baseline em >= 2/3 splits (IC bootstrap excluindo zero).
- RPS/ECE no espaco de brackets melhoram ou ficam iguais.
- "no-temperature" variant ainda apresenta skill positiva vs persistencia em pelo menos 1 CP - prova que ha "informacao atmosferica real" (REQ secao 18 v1).
- Importancia da observacao corrente continua < 0.10.
- Sem violacoes de timestamp em nenhum NWP feature.

**Kill criteria:** se NWP cru ja bate o residual, ou se residual depende exclusivamente de `T_now`, parar e revisitar features de regime/disagreement.

**Mapeamento de requirements:** REQ-MOD-1, REQ-MOD-3, REQ-DAT-5, REQ-AUD-2.

---

## Fase 5 - Calibracao heteroscedastica + confidence audit

**Objetivo:** IC80 confiavel e `confidence_score` calibrado e usavel como gate de stay-out.

**Entregaveis:**
- `core/calibration/conformal.py`: conformal por CP (e opcionalmente por bucket `(month, regime, cp)` com `n_min=200`).
- Janela curta (60-90 dias) auditada + cross-check com janela sazonal de 12 meses (REQ secao 16 v1).
- Curvas risk-coverage e sharpness-vs-calibration em `reports/calibration/<run_id>.md`.
- Teste de heteroscedasticidade: bins por largura do IC e cobertura empirica por bin (REQ-AUD-5).
- `core/confidence/score.py`: confidence_score conforme design 8.3 + isotonic regression.
- `audits/<run_id>/confidence_audit.json` (REQ-CONF-1):
  - ECE <= 0.05,
  - tabela `bracket_match @ coverage in {25%, 50%, 75%, 100%}`.

**Gate de saida:**
- `|coverage_80 - 0.80| < 0.04` (REQ-AUD-2).
- ECE do confidence_score <= 0.05 (REQ-CONF-1).
- Heteroscedasticidade nao-degenerada (REQ-AUD-5).
- Bracket-match em coverage 50% e mensuravelmente maior que em coverage 100% (selective forecasting funciona).

**Kill criteria:** se confidence audit falhar, `confidence_score` **nao pode** ser usado como gate de producao (REQ-CONF-1) - parar e refinar features ou troca de calibrador antes de Fase 8.

**Mapeamento de requirements:** REQ-MOD-4, REQ-CONF-1, REQ-CONF-2, REQ-CONF-3, REQ-AUD-5, REQ-MET-2.

---

## Fase 6 - AR online (opcional)

**Objetivo:** reduzir drift/bias residual sem introduzir leakage.

**Entregaveis:**
- `core/online/ar.py`: AR(7) residual estritamente passado.
- Estado online em `artifacts/state/ar/<date>.json` com backup `<date>.bak.json` antes de cada update (REQ-OPS-5).
- DM-test/walk-forward AR-on vs AR-off vs persistencia.
- Feature flag `ar_online.enabled` em `nzwn/config/model.yaml`.

**Gate de saida:**
- AR-on melhora bias/drift em >= 2/3 splits.
- Cobertura IC80 nao degrada.
- Auditoria forense roda com AR-on e produz verdict identico em causalidade.

**Kill criteria:** se cobertura cai ou se a auditoria detecta leakage por estado online, desabilitar via flag e nao promover.

**Mapeamento de requirements:** REQ-MOD-5, REQ-OPS-5.

---

## Fase 7 - Late spike como alerta

**Objetivo:** adicionar `spike_risk` como sinal operacional (stay-out / block_buy_no), nao como nucleo.

**Entregaveis:**
- `core/spike/labels.py`: gerar `late_spike_l1` (REQ-SPK-1).
- `core/spike/features.py`: features causais (design secao 9).
- `core/spike/model.py`: LightGBM binario + isotonic regression.
- `reports/spike/<run_id>.md`: PR-AUC, recall@FPR<=0.05, ECE (REQ-SPK-3).
- Integracao do `spike_risk` no `confidence_score` (REQ-CONF-2).
- Decision engine usa `spike_risk` para `BLOCK_BUY_NO_LATE_SPIKE`.

**Gate de saida:**
- PR-AUC > prevalencia base (mensuravelmente, IC bootstrap),
- recall@FPR<=0.05 documentado,
- ECE do `spike_risk` <= 0.07,
- Inclusao de `spike_risk` melhora accuracy-vs-coverage do core.

**Kill criteria:** se PR-AUC nao supera baseline (prevalencia + heuristica de slope), tratar `spike_risk` como apenas exibicao/alerta visual no postmortem; nao usar como gate de bloqueio.

**Mapeamento de requirements:** REQ-SPK-1, REQ-SPK-2, REQ-SPK-3, REQ-CONF-2, REQ-DEC-2.

---

## Fase 8 - Shadow trading + EV

**Objetivo:** medir a metrica primaria (REQ-MET-1) sob mecanica de execucao **congelada** (REQ-MET-5) e tuning anti-overfit (REQ-MET-6).

**Pre-requisitos:**
- OPN-1 (auditoria binaria do resolver Polymarket) fechado.
- `contracts/execution.md` (`EXECUTION_VERSION=1.0`) congelado **antes** de rodar qualquer backtest (REQ-MET-5).
- OPN-3 ainda em aberto, sera fechado nesta fase via REQ-DEC-3 + REQ-MET-6.

**Entregaveis:**
- `core/ingest/odds.py`: ingestor de odds Polymarket por `eventUrl` + snapshot SHA256 (REQ-DEC-4). Schema dos contracts: `{name, range_low_int, range_high_int, price_yes, price_no, ts_utc}`.
- `core/decision/market_map.py`: regra unica para mapear `prob_dist` -> `p_yes` por contract:
  - para um contract `c` com range `[k_lo, k_hi]`: `p_yes(c) = sum(prob_dist[k] for k in support_K if k_lo <= k <= k_hi)`,
  - para contract `c == k_exact` (ex.: "Tmax = 19"): `p_yes(c) = prob_dist[k_exact]` (ou 0 se `k_exact not in support_K`),
  - **Hard rule:** `sum(p_yes(c) for c in contracts) <= 1 + epsilon` (mercados Polymarket somam ~1; `epsilon=0.02` por imprecisao das odds).
- `core/decision/engine.py`: implementacao completa do design secao 10.
- `core/decision/shadow_exec.py`: implementacao do simulador descrito em design 10.1, lendo `contracts/execution.md` e produzindo `equity_curve.parquet` + `trades.parquet`.
- `core/decision/threshold_tuning.py`: otimizacao via funcao-objetivo congelada em `contracts/objective.md` (REQ-DEC-3) usando **nested walk-forward** (design 10.2, REQ-MET-6):
  - configuracao final escolhida em VALIDATION,
  - aplicada exatamente uma vez ao TEST,
  - logar todas as configuracoes avaliadas em `artifacts/tuning/<threshold_set_id>/results.parquet`.
- Backtest de execucao shadow + EV realizado + drawdown + Sharpe.
- `reports/shadow/<run_id>.md`:
  - identificacao explicita de `EXECUTION_VERSION` e `threshold_set_id`,
  - EV esperado vs realizado por bucket de `confidence_score`,
  - calibracao de probabilidades de trade,
  - drawdown e curva de equity,
  - tabela coverage (REQ-MET-2).

**Gate de saida:**
- EV realizado consistente com EV esperado dentro de IC95% bootstrap em >= 2/3 splits TEST.
- Coverage atingida >= alvo da funcao-objetivo (REQ-DEC-3).
- Sem dependencia de janelas contaminadas (auditoria forense ainda passa com decisoes incluidas).
- `audits/<run_id>/h0_verdict.json` cobre fase 7 (economic_edge) com `passed=true`.
- Nenhum hiperparametro do core (incluindo `tau`, `safety_margin`) foi alterado durante o tuning de thresholds (REQ-MET-6).

**Kill criteria:**
- EV realizado consistentemente abaixo de zero ou fora dos ICs por > 1 split TEST -> nao promover; voltar para Fase 5/7 e revisar calibracao/spike.
- `sum(p_yes(c)) > 1 + 0.02` em > 5% dos snapshots de odds -> revisar `market_map.py` e/ou snapshot de odds antes de seguir.
- Tuning rodado mais de 1x sobre o mesmo TEST split -> versao invalidada; novo `threshold_set_id` exige novo TEST split.

**Mapeamento de requirements:** REQ-MET-1, REQ-MET-5, REQ-MET-6, REQ-DEC-1, REQ-DEC-2, REQ-DEC-3, REQ-DEC-4, REQ-AUD-1.

---

## Cronograma sugerido (calendario)

| Semana | Atividades |
|--------|-----------|
| 1 | Fase 0 (setup), inicio Fase 1 (parser CSV + timeutil + DST tests) |
| 2 | Fase 1 (labels Tmax + builder CP-aware + EDA) |
| 3 | Fase 2 (baselines + CLI + harness H0) |
| 4 | Fase 2 conclusao + (opcional) Fase 2b TAF |
| 5-6 | Fase 3 (Ridge band-aware + gates pre-registrados) |
| 7-9 | Fase 4 (NWP ingest + residual learning) |
| 10-11 | Fase 5 (conformal + confidence audit) |
| 12 | Fase 6 (AR online, opcional) |
| 13-14 | Fase 7 (late spike) |
| 15-18 | Fase 8 (shadow trading + EV) |

Buffer de 2-3 semanas para retrabalho dos kill criteria.

---

## Decisoes em aberto que bloqueiam fases

| Pendencia | Bloqueia | Acao |
|-----------|----------|------|
| OPN-1a (validacao **minima** do resolver: estacao + tz + janela) | **Fase 1** | confirmar `NZWN`, `Pacific/Auckland`, `00:00-23:59 local`; gravar em `contracts/resolver.md` |
| OPN-5 (fonte NWP) | **Fase 4** | escolher entre ECMWF / GFS / blending; documentar custos e cobertura historica |
| OPN-1 (auditoria binaria de Q vs Polymarket) | **Fase 8** | rodar miner de >=30 dias (decimal vs inteiro publicado); abrir issue se divergencia > 1% |
| OPN-3 (cutoffs operacionais) | **Fase 8** | aprender via REQ-DEC-3 + REQ-MET-6 (nested walk-forward) |
| OPN-4 (CP padrao) | (n/a) | **congelado** em REQ-CON-6: `CP_SET = [20:00, 21:00, 22:00, 23:00] UTC`; CP operacional = `23:00` |

---

## Saidas obrigatorias por execucao do pipeline

A cada `tmax forecast` em qualquer fase >= 2, o sistema deve emitir:
- `artifacts/forecasts/<run_id>.parquet`
- `artifacts/logs/<run_id>.jsonl`
- `reports/postmortem/<date_local>.md` (no D+1)

A cada `tmax audit`, deve emitir:
- `audits/<run_id>/h0_verdict.json` (REQ-AUD-1)
- `reports/audits/<run_id>/*.md`

Sem qualquer um destes, a execucao e considerada FAIL (REQ-AUD-1, REQ-OPS-3, REQ-OPS-4).
