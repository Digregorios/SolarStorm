# Tasks - Polymarket Tmax Forecaster (NZWN)

> **Spec version:** 1.0
> **Idioma:** PT-BR (ASCII em CLIs/logs/paths)
> **Companion:** `requirements.md`, `design.md`, `implementation-plan.md`

Backlog acionavel agrupado por fase. Cada task tem:
- ID `T-FASE-N`,
- referencia(s) de requirement (`REQ-*`),
- descricao curta acionavel,
- criterio de "done" objetivo.

**Convencao:** marcar `[x]` quando done; `[~]` quando em progresso; `[!]` quando bloqueado (com nota).

---

## STATUS RECONCILIADO (2026-05-31) - leia antes de tudo

> O plano abaixo ficou dessincronizado da realidade (checkboxes de Fases 0-2 ainda `[ ]`
> embora o codigo e os relatorios existam ha tempo). Esta secao e a fonte de verdade do
> estado real; os checkboxes por-task foram atualizados para refleti-la.

| Fase | Estado real | Evidencia |
|------|-------------|-----------|
| 0 Setup + contratos | **DONE** | repo + contratos congelados + guards (ascii/reverse-import/contract-version) em CI |
| 1 Data + labels + **EDA** | **DONE** | `reports/eda/*` (tmax-hour, early-peak, coverage, decimal-vs-int) + EDA rica Etapa 1 (`reports/eda/`, `reports/regime/`). 99.7% day_complete, 0% fallback, 0% discrepancia decimal-vs-int (kill criteria PASS) |
| 2 Baselines + harness H0 | **DONE** | persistencia>climatologia perto do EOD; `reports/h0_verdict.json` |
| 3 Ridge band-aware | **DONE** | `reports/phase3.md`; REQ-MET-4 PASS 3/3; corr_diff diagnostico |
| 4 NWP residual | **DONE** | `reports/phase4.md`; phase4_ready=True; ablation pareado pooled 3/3 |
| 5 Calibracao/confidence | **CLOSED NOT READY** | `reports/phase5_closure.md`; het gate REQ-AUD-5 nunca passou; IC80/confidence diagnostico, fora do trading |
| 6 AR online | PARCIAL | AR(7)+estado feitos; DM-test (T-6-3) adiado |
| 7 Late spike | **DONE** | `reports/spike/*`; REQ-SPK-3 PASS 3/3 (PR-AUC ~0.95) |
| 8 Decisao + odds live | OFFLINE DONE | logica + sizing + odds live; EV realizado e live-gated. **CONGELADO (ver abaixo)** |

### FOCO TOTAL: o preditor de Tmax (regra de governanca, 2026-05-31)

> **Telhado antes da poltrona.** Nenhuma entrega nova de execucao/Polymarket (Kelly, EV,
> decision-line, brackets, resolver, trading states) ate o preditor avancar. A Fase 8 esta
> CONGELADA exceto o minimo para nao quebrar contratos/testes. O preditor de Tmax e o unico
> foco ate o proximo gate de modelo ser batido.

O core JA vence baselines (REQ-MET-4 PASS; `reports/core_predictor_status.md`: Ridge bate o
melhor baseline por MAE 3/3 splits em todos os 4 CPs; CP23 MAE ~0.70 degC). A frente de preditor
agora e **melhorar o sinal**, nao re-provar o core nem polir execucao. Problemas abertos REAIS,
em ordem de prioridade:

1. **Lado high-risk (late-warming):** o `analog_retrieval_audit` mostrou que analogos capturam o
   que o Ridge/logistico erram (non-calm high-risk lift 1.34-1.42; analog_confidence resolve g5).
   Proximo: construir o `analog_high_risk_arm_v0` (elegivel) e medir ganho de MAE/bracket-match em
   dias non-calm, walk-forward. Isto e PREDITOR, nao execucao.
2. **Lado low-risk (dias travados):** `calm_day_filter_v0` (GO=True) - usar como gate para nao
   overcorrigir; medir se estreitar a distribuicao em dias calmos melhora RPS sem perder coverage.
3. **Distribuicao calibravel (o "telhado"):** Fase 5 condicional (heteroscedastica) e o problema
   genuinamente aberto. O ponto e forte, o intervalo nao. Sem isto a distribuicao para brackets e
   fraca. `ridge_conformal_minimal` e um stopgap defensavel (coverage 0.86-0.91), nao um passe.
4. **NWP em leads mais cedo:** Phase 4 mostrou ganho pooled; o ganho maior esta em 20-22Z. Explorar
   so depois que 1-3 avancarem.

Tudo o que NAO for 1-4 (ou um kill criterion de plano) e fora de foco ate novo aviso.

---

## Fase 0 - Setup e contratos congelados

### T-0-1: Inicializar repositorio e estrutura de pastas
- [ ] Criar diretorios listados em design 2 (`core/`, `nzwn/`, `audits/`, `experiments/`, `contracts/`, `artifacts/`, `reports/`, `tests/`, `references/legacy/`).
- [ ] Mover/copiar v1 markdown para `references/legacy/polymarket-tmax-forecaster-v1.md`.
- [ ] Criar `data_sources.md` em `references/legacy/` com atribuicao IEM ASOS.
- **Done:** `tree -L 2` mostra a estrutura. `references/legacy/` contem v1 + atribuicao.
- **REQ:** REQ-REP-1, REQ-SEC-3.

### T-0-2: Configurar projeto Python
- [ ] Criar `pyproject.toml` com Python `>=3.11,<3.12` e dependencias pinadas (ver design 3).
- [ ] Lockfile (`uv.lock` ou `requirements.lock.txt`) gerado e commitado.
- [ ] `ruff.toml` + `mypy.ini` (strict em `core/` e `nzwn/`).
- **Done:** `pip install -e .` instala sem erros; `ruff check .` passa em repo vazio.
- **REQ:** REQ-SEC-2.

### T-0-3: Congelar contratos
- [ ] `contracts/quantization.md` com `Q_VERSION=1.0`, B(k), Q(x), exemplos numericos.
- [ ] `contracts/imputation.md` skeleton (preenchido na Fase 1 conforme features apareçam).
- [ ] `contracts/objective.md` com a funcao-objetivo congelada (default proposto: `max(EV) sujeito a max_drawdown <= 5%`; aprovar antes de avancar para Fase 8).
- [ ] `contracts/features.md` skeleton.
- **Done:** os 4 contratos existem com versao e timestamp; CI inclui guard que falha se contrato muda sem bump de versao.
- **REQ:** REQ-CON-1, REQ-DAT-3, REQ-DEC-3.

### T-0-4: Configuracao NZWN
- [ ] `nzwn/config/station.yaml`: `icao: NZWN`, lat/lon, `tz: Pacific/Auckland`, `cp_operacional_utc: "23:00"`, lista de CPs avaliados (ex.: `[20Z, 21Z, 22Z, 23Z]`).
- [ ] `nzwn/config/features.yaml` skeleton.
- [ ] `nzwn/config/model.yaml` com seeds fixas (random=42, numpy=42, lightgbm.seed=42, etc.).
- **Done:** YAMLs validados por schema (pydantic ou jsonschema).
- **REQ:** REQ-CON-4, REQ-MOD-6.

### T-0-5: CI baseline com guards
- [ ] `.github/workflows/ci.yml`: jobs `lint` (ruff), `typecheck` (mypy), `test` (pytest), `guards`.
- [ ] Guard `reverse_import`: script que parseia AST e falha se `core/` ou `nzwn/` importam de `audits/`, `experiments/` ou `artifacts/scratch/`. Inclui teste **negativo** (commit que viola e validar fail).
- [ ] Guard `ascii_only`: script que falha em path/log/contract com caracteres unicode.
- [ ] Guard `determinism` (skipped por enquanto, ativado na Fase 3): treina com seed fixa duas vezes e compara SHA256.
- **Done:** CI verde no commit inicial; PR de teste violando reverse-import falha.
- **REQ:** REQ-AUD-3, REQ-OPS-2, REQ-REP-3, REQ-MOD-6.

### T-0-6: Skeleton de logs e CLI
- [ ] `core/io/logging.py` com structlog -> JSONL conforme schema REQ-OPS-3.
- [ ] `core/cli/__main__.py` (typer) com subcomandos placeholder: `forecast`, `postmortem`, `update-ar`, `audit`, `report` (todos retornam exit-code 2 "not implemented" por enquanto).
- **Done:** `py -3 -m core.cli forecast --help` mostra ajuda; logs JSONL valido.
- **REQ:** REQ-OPS-1, REQ-OPS-2, REQ-OPS-3.

### T-0-7: Congelar CP_SET e validacao minima do resolver (OPN-1a)
- [ ] Em `nzwn/config/station.yaml` definir explicitamente:
  ```yaml
  cp_set_utc: ["20:00", "21:00", "22:00", "23:00"]
  cp_operacional_utc: "23:00"
  ```
- [ ] Em `contracts/resolver.md` (versao minima v0.1, **OPN-1a**) registrar:
  - estacao = `NZWN`,
  - timezone = `Pacific/Auckland`,
  - janela do dia = `00:00:00 - 23:59:59 local`.
- [ ] Adicionar pydantic schema validator em `core/contracts/station.py` que rejeita CP fora de `HH:00` UTC.
- **Done:** rodar `py -3 -c "from core.contracts.station import load; load('nzwn/config/station.yaml')"` retorna sem erro; CP fora do padrao falha com mensagem clara.
- **REQ:** REQ-CON-6, OPN-1a (validacao minima de Fase 1).

---

## Fase 1 - Data contracts + labels + EDA

### T-1-1: Parser de NZWN.csv
- [ ] `core/ingest/iem_csv.py::read_iem_csv(path) -> polars.DataFrame`.
- [ ] Mapping conforme design 4.2 (M -> NaN; tmpf decimal preservado).
- [ ] Extracao do inteiro °C do `metar` cru via regex `r"\s(M?\d{2})/(M?\d{2})\s"` (cuidado com `M` para temperaturas negativas).
- **Done:** parser le `NZWN.csv` em < 5s e retorna 112.190 linhas; testes unitarios cobrem temperatura negativa, missing, formato `19/14` e `M02/M05`.
- **REQ:** REQ-DAT-3, REQ-CON-3.

### T-1-2: Snapshot deterministico do METAR
- [ ] `core/ingest/snapshot.py::snapshot_csv_by_local_day(csv_path, station, out_root)` particiona em `artifacts/raw/metar/<station>/<yyyy>/<mm>/<dd>.csv`.
- [ ] `manifest.jsonl` por dia: `{date_local, sha256, n_rows, source_csv_sha256}`.
- [ ] Idempotencia: rodar 2x produz hashes iguais.
- **Done:** snapshot completo do CSV historico gravado; manifest valido; teste de idempotencia passa.
- **REQ:** REQ-DAT-1.

### T-1-3: Time utils com testes DST
- [ ] `core/io/timeutil.py`: `to_utc`, `to_local`, `day_local_window(date_local) -> (utc_start, utc_end)`.
- [ ] Testes unitarios em `tests/unit/test_dst.py`:
  - 2024-09-29 (inicio DST) e 2024-04-07 (fim DST) - 2 anos cobertos no minimo,
  - dia anterior, dia da transicao, dia seguinte, em ambas direcoes,
  - assertiva: `day_local_window` cobre exatamente 23h ou 25h conforme transicao.
- **Done:** todos testes DST passam.
- **REQ:** REQ-CON-4.

### T-1-4: Tabela canonica metar_observations
- [ ] `core/ingest/observations.py`: pipeline completo `iem_csv -> snapshot -> metar_observations`.
- [ ] Cross-check `Q(round((tmpf-32)*5/9))` vs `tmp_c_int` extraido do metar; gerar `reports/eda/decimal_vs_int_check.md`.
- [ ] Persistir `metar_observations.parquet` particionado por `date_local`.
- **Done:** tabela existe; discrepancia documentada e < 0.5%.
- **REQ:** REQ-CON-3, REQ-DAT-3.

### T-1-5: Labels Tmax e late spike
- [ ] `core/labels/tmax.py::build_tmax_labels(date_local) -> TmaxLabel`.
- [ ] Cobrir 24h locais; calcular `tmax_int`, `tmin_int`, `tmax_ts_*`, `day_complete`.
- [ ] `late_spike_l1` parametrizado por `cp_op` (default `23 UTC`).
- [ ] Persistir `tmax_labels.parquet`.
- **Done:** labels para todos os dias completos do dataset; testes em dias com SPECI noturno e em dias com transicao DST.
- **REQ:** REQ-CON-3, REQ-CON-4, REQ-SPK-1.

### T-1-6: Dataset builder CP-aware
- [ ] `core/features/builder.py::build_cp_features(date_local, cp_utc) -> CPFeatures`.
- [ ] Usa `closed='left'` em todos os rolling.
- [ ] Atribui `feature_max_ts_utc` e valida `<= cp_utc`.
- [ ] Particiona por `date_local`; uma linha por `(date_local, cp_utc)`.
- **Done:** runner reproduzivel; rodar 2x gera mesmo SHA256.
- **REQ:** REQ-DAT-2, REQ-CON-5, REQ-AUD-4.

### T-1-7: Baselines persistencia + climatologia
- [x] `core/baselines/persistence.py`: `t_so_far_max_c_int` projecao via lag direto.
- [x] `core/baselines/climatology.py`: tabela horaria smoothed treinada em janela >= 12 meses do train split.
- **Done:** RECONCILED 2026-05-31 - baselines com testes; usados em phase3/phase4/core_predictor_status.
- **REQ:** REQ-MET-3.

### T-1-8: EDA inicial
- [x] Script em `experiments/eda/intro.py` que gera **tabelas** (parquet/csv) e markdown:
  - tabela `tmax_hour_local_by_month.csv` com `(month, p10, p25, p50, p75, p90)` da hora local do Tmax,
  - tabela `early_peak_by_month.csv` com taxa de early peak (`tmax_hour_local < 12`) e outlier (`tmax_hour_local in [0,6) or [22,24)`),
  - tabela `coverage_by_month.csv` com `n_total, n_complete, ratio_complete` (REQ-CON-7),
  - tabela `tmax_distribution_by_month.csv` com histograma `(month, k, count)`.
- [x] `reports/eda/intro.md` com pelo menos 10 numeros chave inline + as 4 tabelas linkadas.
- [x] Plots PNG sao **opcionais** e nao fazem parte do criterio de done.
- **Done:** RECONCILED 2026-05-31 - 4 tabelas em `reports/eda/` + EDA rica Etapa 1 (3 agentes: morning_predictors, regime_path, month_decade). EDA = Fase 1 CONCLUIDA.
- **REQ:** REQ-MET-2 (parcial), REQ-CON-7.

### T-1-9: Golden tests Fase 1
- [ ] Selecionar 3 dias representativos (dia tipico de verao, dia tipico de inverno, dia com transicao DST).
- [ ] Congelar input + output esperado em `tests/golden/phase1/`.
- [ ] `pytest -k golden_phase1` valida match exato.
- **Done:** golden tests passam em CI.
- **REQ:** REQ-REP-2.

### T-1-10: Implementar day_complete (REQ-CON-7)
- [x] `core/labels/completeness.py::is_day_complete(date_local) -> tuple[bool, dict]` retorna `(flag, motivos)` com criterios de REQ-CON-7:
  - `n_obs >= 40` em 24h locais,
  - `max_gap_minutes <= 120`,
  - 1 obs em cada um dos 4 quartis do dia local.
- [x] Tabela de cobertura mensal em `reports/eda/coverage.md` (markdown + csv com `n_total, n_complete, ratio_complete, motivos_top3`).
- [x] Test unit cobre: dia normal, dia com gap longo, dia sem manha, dia incompleto.
- **Done:** RECONCILED 2026-05-31 - 99.7% day_complete global (`reports/eda/coverage_by_month.csv`); kill criterion (<=5% False) PASS.
- **REQ:** REQ-CON-7, REQ-MET-2.

### T-1-11: Implementar fallback policy + tracking (REQ-CON-8)
- [x] `core/labels/parse_metar.py` segue exatamente o pseudocodigo da design 4.1.2.
- [x] Tracking: incrementar contadores `parse_ok`, `parse_imputed`, `parse_missing`, `parse_implausible_value` em metricas estruturadas.
- [x] Relatorio `reports/eda/decimal_vs_int_check.md` (markdown + csv) com:
  - taxa de discrepancia (`Q(round((tmpf-32)*5/9))` vs `T_obs_int`) por mes,
  - taxa de fallback por mes,
  - exemplos textuais de 5 mensagens com regex falhando.
- [x] CI guard `tests/integration/test_fallback_kill.py` que falha se `fallback_rate_global > 0.5%` ou `discrepancia_global > 0.5%` no dataset commitado.
- **Done:** RECONCILED 2026-05-31 - 0% fallback, 0% discrepancia decimal-vs-int (`reports/eda/decimal_vs_int_check.md`); ambos kill criteria PASS.
- **REQ:** REQ-CON-8, REQ-CON-3.

---

## Fase 2 - Baselines + harness de auditoria

### T-2-1: CLI forecast (baselines)
- [ ] `core/cli/forecast.py`: emite `forecasts.parquet` baseado em climatologia + persistencia + `prob_dist` **empirica condicional** (design 8 - contrato de baselines):
  - `P(k_eod = k | month, cp, k_cp)` com Laplace `alpha=1`,
  - fallback marginal `(month, cp)` quando `n < 30`,
  - truncamento ao `support_K` (design 4.5.1).
- [ ] **Proibido em `core/`** prob_dist parametrico Gaussiano (vai para `experiments/baselines_gaussian/` como ablation rotulada).
- [ ] `--dry-run` valida sem persistir.
- **Done:** `tmax forecast --station NZWN --date 2025-12-01 --cp 23` emite forecast valido com `prob_dist` somando 1.0 sobre `support_K`.
- **REQ:** REQ-OPS-1, REQ-MOD-1.

### T-2-2: CLI postmortem D+1
- [ ] `core/cli/postmortem.py`: compara forecast vs truth, emite `reports/postmortem/<date_local>.md`.
- [ ] Tabela `bracket_match @ coverage in {25%, 50%, 75%, 100%}`.
- **Done:** postmortem para um dia exemplo gerado e validado.
- **REQ:** REQ-OPS-4, REQ-MET-2.

### T-2-3: Harness de auditoria forense
- [ ] `audits/run_h0_audit.py` orquestra as 7 fases em modo CLI.
- [ ] Fase 1 (lead-time): `audits/phases/lead_time.py`.
- [ ] Fase 2 (frozen obs): `audits/phases/frozen_obs.py` - varre features e checa `last_input_ts <= cp_utc`.
- [ ] Fase 3 (counterfactual same-temp): `audits/phases/counterfactual.py`.
- [ ] Fase 4 (no-temperature model): placeholder, ativado em Fase 3 do plano.
- [ ] Fase 5 (horizon degradation): `audits/phases/horizon.py`.
- [ ] Fase 6 (extreme spike): `audits/phases/extreme_spike.py`.
- [ ] Fase 7 (economic_edge): placeholder, ativado em Fase 8.
- [ ] Aggregator que emite `audits/<run_id>/h0_verdict.json`.
- **Done:** roda em baselines e produz verdict file valido.
- **REQ:** REQ-AUD-1.

### T-2-4: Reverse-import guard end-to-end
- [ ] Test que cria temp file `core/test_guard.py` com `from audits import x` e valida que `pytest` e o pre-commit falham.
- **Done:** caso negativo coberto.
- **REQ:** REQ-AUD-3.

### T-2-5: Logs JSONL completos
- [ ] Eventos enumerados (design 14): `ingest.start`, `ingest.snapshot.write`, `dataset.build`, `model.predict`, `calibration.apply`, `decision.emit`, `audit.phase.<n>.done`.
- [ ] Cada evento tem `run_id`, `cp_utc`, `cp_local`, `tz_name`, `sha256_inputs[]`.
- **Done:** validador de schema em `tests/integration/test_logs_schema.py`.
- **REQ:** REQ-OPS-3.

---

## Fase 2b (opcional) - TAF como alerta

### T-2b-1: Snapshot bruto de TAF
- [ ] `core/ingest/taf.py::snapshot(...)` (apenas se feed disponivel).
- **REQ:** REQ-DAT-4.

### T-2b-2: Parser TAF
- [ ] `core/ingest/taf_parser.py`: segmentos com (issued_time, valid_from, valid_to) + flags.
- **REQ:** REQ-DAT-4.

### T-2b-3: Causalidade do TAF
- [ ] Test: nenhum TAF com `issued_time > cp_utc` aparece em features.
- **REQ:** REQ-DAT-4.

### T-2b-4: Integracao em confidence
- [ ] Adicionar features de TAF ao `confidence_score` (somente).
- **REQ:** REQ-CONF-2.

---

## Fase 3 - Ridge band-aware

### T-3-1: Implementar loss band-aware
- [ ] `core/models/loss.py::band_aware_loss(y_pred, y_true_int, alpha, mode)`.
- [ ] Variante `linear` e `quadratic`. Documentar em `contracts/features.md` (escolha default).
- **Done:** unit tests cobrindo (`y_pred in B(k)`), (`y_pred = k - 0.5`), (`y_pred fora`).
- **REQ:** REQ-MOD-2.

### T-3-2: Ridge sobre delta vs climo
- [ ] `core/models/ridge_band.py`: usa Ridge convencional para fit e band-aware loss apenas para selecao de hiperparametros / scoring.
- [ ] Hiperparametros via grid search com seed fixa.
- **Done:** modelo treinado em train split; predicao gera `mu_dec`.
- **REQ:** REQ-MOD-1, REQ-MOD-2.

### T-3-3: Walk-forward CV
- [ ] `core/eval/cv.py`: expanding-window com >= 3 splits.
- [ ] IC bootstrap (>=1000 reamostragens) por metrica.
- **Done:** relatorio `reports/cv/ridge_band.md` com tabelas por split.
- **REQ:** REQ-MET-3.

### T-3-4: Gates anti-nowcaster pre-registrados
- [ ] `audits/gates.py` define os limiares fixos da REQ-AUD-2.
- [ ] CI step `gates_check` que le `audits/<run_id>/h0_verdict.json` e falha se algum gate violado.
- **Done:** Ridge passa todos os 7 gates em >= 2/3 splits.
- **REQ:** REQ-AUD-2.

### T-3-5: Counterfactual same-temp
- [ ] Gerar pares (mesmo `t_so_far_max_c_int`, regimes diferentes).
- [ ] Computar AUC e Wasserstein das previsoes.
- **Done:** AUC > 0.70.
- **REQ:** REQ-AUD-2.

### T-3-6: No-temperature variant
- [ ] Treinar Ridge sem `t_so_far_max_c_int`, sem `tmpf`, sem `Tmax(D-1)`.
- [ ] Reportar skill vs persistencia.
- **Done:** skill > 0 com IC95% em pelo menos 1 CP.
- **REQ:** REQ-AUD-2 (relacionado a no-temperature requirement).

### T-3-7: Determinism check ativado
- [x] CI roda dois treinos com seed 42 e compara SHA256 das predicoes
  (`tests/unit/test_determinism.py`, gate unitario em vez de CLI; cobre REQ-MOD-6).
- **Done:** zero diff (sha256 identico nos dois treinos do residual LGBM).
- **REQ:** REQ-MOD-6.

### T-3-8: Permutation importance gate
- [ ] Computar `permutation_importance` para `t_so_far_max_c_int` e `Tmax(D-1)`.
- [ ] Falha CI se `I_T_obs >= 0.10` ou `I_Tmax_dminus1 > 0.10`.
- **Done:** thresholds enforced.
- **REQ:** REQ-AUD-2, REQ-AUD-6.

---

## Fase 4 - NWP residual learning

### T-4-1: Decisao OPN-5 (fonte NWP)
### T-4-1: Decisao OPN-5 (fonte NWP) - **CLOSED**
- [x] Documentar opcoes (ECMWF, GFS, ensemble), custos, cobertura historica.
- [x] Aprovar fonte; gravar em `contracts/nwp_source.md`.
- **Done:** decisao registrada em `contracts/nwp_source.md` v1.0 (Open-Meteo HFAPI +
  Single Runs; v1 launch set = ECMWF IFS HRES + NCEP GFS; safety_margin=60 min;
  scale-up para 4 modelos exige bump de NWP_SOURCE_VERSION).
- **REQ:** OPN-5.

### T-OPN-5a: HFAPI vs Single Runs cross-check (causality leakage validation)
- **BLOCKED UNTIL:** T-4-2 concluida (precisa de ingestor para os dois endpoints).
- **v1.1 (code review 2026-05-29):** cross-check roda na **agregacao max-de-trajetoria**
  (design 4.5.2.1), nao numa valid_time unica.
- [ ] `scripts/opn5a_hfapi_vs_single_runs.py`: rodar Phase 4 baseline com HFAPI vs
  Single Runs ECMWF no overlap **2024-03-01 .. 2025-12-31**.
- [ ] Comparar bracket-match, RPS, ECE com bootstrap CI95 paired.
- [ ] Per-split sanity check: split 1 (HFAPI only, 2023) gain over baselines NAO pode
  ser > 1.5x o gain medio em splits 2-3 (com SingleRuns disponivel).
- [ ] **Probe GFS-2023 real (AWS noaa-gfs-bdp-pds)** antes de aceitar o drop do split-1;
  so dropar se um ensemble causal simetrico de 2 modelos para 2023 for genuinamente
  impossivel. Se dropar, propagar regra `>= 2/2` as fases seguintes.
- [ ] Emitir `reports/opn5a_cross_check.md` com tabela final + verdict.
- **Acceptance** (per `contracts/nwp_source.md` secao "Cross-check obligation"):
  1. `|bracket_match_HFAPI - bracket_match_SingleRuns|` dentro de IC95 paired,
  2. `|RPS_HFAPI - RPS_SingleRuns|` dentro de IC95 paired,
  3. `|ECE_HFAPI - ECE_SingleRuns| <= 0.02`,
  4. per-split sanity satisfeito.
- **Kill criterion**:
  - se 1-3 PASS e 4 PASS -> HFAPI e fonte primaria; Phase 4 desbloqueia
  - se 1-3 PASS e 4 FAIL -> HFAPI restrita a features menos sensiveis (spread/disagreement);
    forecast primario via SingleRuns ECMWF (split 1 sai do kill criterion)
  - se 1-3 FAIL -> HFAPI rejeitada; pipeline so com SingleRuns (perde split 1)
- **REQ:** OPN-5a, REQ-DAT-5, REQ-MET-1.

### T-4-1b: Pre-registered ablation HRES-only vs multi-model (design 19.2)
- **BLOCKED UNTIL:** T-4-2 concluida e T-OPN-5a verdict emitido.
- [ ] Treinar 5 variantes em walk-forward Phase 4 splits:
  A) HRES-only, B) GFS-only, C) UKMO-only (so se scale-up), D) ICON-only (so se scale-up),
  E) Multi-model blend (default).
- [ ] Reportar bracket-match / RPS / ECE com bootstrap IC95 paired por par de variantes.
- [ ] Emitir `reports/phase4_nwp_ablation.md` com NWP_SOURCE_VERSION no header.
- **Acceptance:**
  - "HRES-only como pilar principal" so e aprovado se ganhar em >= 2/3 splits vs cada
    outra variante com IC95 paired excluindo zero E sem regredir RPS/ECE.
  - Caso contrario, default = Multi-model blend (variante E) e HRES e "mais um membro".
- **REQ:** REQ-AUD-2, REQ-MET-3, REQ-MET-4, design 19.2.

### T-4-2: Ingestor NWP forecast (atualizado)
- **BLOCKED UNTIL:** T-4-1 concluida (decisao OPN-5 sobre fonte NWP).
- [x] `core/ingest/nwp.py` snapshot writers + `select_nwp_v1` (CP-causal).
- [x] Suporta os dois endpoints: `historical-forecast-api` e `single-runs-api`.
- [x] Guarda snapshots por `(model, run_time_utc, lead_h)` + SHA256, com `endpoint` e
  `run_time_utc` (issued_time) explicitos no row (reforco A do open-meteo).
- [x] Validacao causal: `run_time_utc <= cp_utc - safety_margin` (60 min em v1, do
  `model.yaml`); violacao = `RuntimeError` (reforco B).
- [x] Validacao adicional: `valid_time_utc > run_time_utc` (lead_h >= 0 no parse).
- [x] Implementa `select_nwp_v1(cp_utc, target_valid_utc, model)` conforme design 4.5.2.
- [x] Frozen observation test (audit phase 2) extendido com check NWP-especifico
  (`audits/phases/nwp_timestamps.py`).
- **Done:** ingestor HFAPI rodando 2020-2026 (432 particoes); selecao deterministica
  testada (`tests/unit/test_nwp_ingest.py`). NOTA: backfill Single Runs ainda nao
  executado (necessario p/ T-OPN-5a).
- **REQ:** REQ-DAT-5 (atualizado), design 4.5.2.

### T-4-3: Features NWP (mean/spread/disagreement)
- [x] `core/features/nwp.py`: media de ensemble, spread (np.std), disagreement_score,
  features de trajetoria (max/slope/range pre-CP) + anchor max-de-trajetoria.
- **Done:** features integradas a `build_training_panel` (NWP_FEATURE_COLUMNS).
- **REQ:** REQ-MOD-3.

### T-4-4: Residual LightGBM
- [x] `core/models/residual_lgbm.py`: target = `truth - NWP_baseline`.
- [x] Seeds fixas (42); early stopping deterministico (deterministic=True, num_threads=1).
- **Done (codigo):** modelo treinado e ligado a `phase4_evaluate`. **Aceitacao
  pendente:** "supera baseline em >= 2/3 splits" foi RE-ESCOPADO pelo reframe v1.1 para
  ablation pareado (IC95 lo>0); verdict so apos re-run (T-4-8 Passo 8/9).
- **REQ:** REQ-MOD-1, REQ-MOD-3, REQ-MOD-6.

### T-4-5: Ablations
- [ ] Tabela em `reports/cv/phase4_ablations.md`: NWP cru / NWP+residual sem intraday / NWP+residual completo / Ridge baseline.
- **Done:** tabela publicada.
- **REQ:** REQ-MET-3.

### T-4-6: No-temperature variant Fase 4
- [ ] Repetir T-3-6 sobre o residual LGBM.
- **Done:** documentacao em `reports/audits/no_temp_phase4.md`.

### T-4-7: Regimes GMM congelados
- [ ] `nzwn/regimes/train_gmm.py`: treina 6-8 componentes em features de amanhecer (sin/cos vento, intensidade, QNH, dQNH 6h).
- [ ] Seed fixa; salvar `gmm_v1.pkl` + `manifest.json`.
- [ ] Em producao, GMM e read-only; nao retreinar sem versionar.
- **Done:** GMM congelado; features `regime_id`, `regime_proba` integradas.
- **REQ:** Design 7 (REQ - secao 21.10 v1).

### T-4-8: Reframe Fase 4 (code review 2026-05-29) - **criterion_version 1.1**
> Reframe pre-registrado: NWP = provedor de features forward + incerteza, nao anchor
> competindo com Ridge. Ordem de execucao em design 29.4; criterio de saida em 29.5.
- [x] **Passo 0** - travar C1-C4 + bumps (NWP_SOURCE_VERSION 1.1, MODEL_VERSION,
  criterion_version 1.1) em design/requirements/contracts. **[feito nesta task]**
- [x] **Passo 1** - fix bug i_t_obs anchor (`phase4_evaluate.py` permutation predict usa
  anchor NWP, nao `clim_test`) + teste de regressao. **[tests/unit/test_i_t_obs_anchor.py]**
- [x] **Passo 2** - config-as-contract: loader le `model.yaml` e da assert que
  `open_meteo_id` casa com `ModelSpec`; teste config<->codigo; corrigir valor do yaml.
  **[load_nwp_model_specs + tests/unit/test_nwp_config_contract.py]**
- [x] **Passo 3** - auditoria de climatologia causal (feature `clim_tmax_c_dec` E
  `target_delta` por split, train-only) como teste de CI.
  **[assert_causal_climo + tests/unit/test_causal_climatology.py]**
- [x] **Passo 4** - anchor max-de-trajetoria causal (design 4.5.2.1) + gate de CI de
  leakage (`run_time <= cp - safety_margin`). Uma fonte causal por periodo (anchor+spread).
  **[select_max_trajectory_anchor + tests/unit/test_maxtraj_anchor.py + test_nwp_leakage_gate.py]**
- [x] **Passo 5** - pre-registro com dente: `contracts/phase4_preregistration.md` +
  sha256; `phase4_evaluate` falha se hash runtime != committado.
  **[core/eval/preregistration.py + tests/unit/test_preregistration.py]**
- [ ] **Passo 6** - T-OPN-5a na agregacao max-de-trajetoria + probe GFS-2023.
  **[PENDENTE - ver T-OPN-5a; bloqueio de ambiente: sem decoder GRIB para o probe AWS]**
- [x] **Passo 7** - `corr_diff` em anomalias (climo causal) rebaixado a diagnostico
  (reportado, nao bloqueia) + atualizar testes.
  **[DIAGNOSTIC_ONLY_GATES + collect_gate_violations; tests/unit/test_review_v2_fixes.py]**
- [ ] **Passo 8** - re-run `phase4_evaluate` -> report estratificado por lead (28.6) +
  `h0_verdict.json` (com pre-reg hash + criterion_version). **[PENDENTE - bloqueado por Passo 6]**
- [ ] **Passo 9** - avaliar contra 29.5 (ablation pareado, IC95 lo>0 em >=2/3 ou >=2/2,
  gates sobreviventes intactos). Passa -> Fase 5. Falha honesta -> Plano B (21.7).
  **[PENDENTE - depende dos resultados do re-run, Passo 8]**
- [x] Determinismo no CI desde ja (REQ-MOD-6): dois treinos, SHA256 identico.
  **[tests/unit/test_determinism.py]**
- **Codigo (logica de aceitacao) implementado:** acceptance = ablation pareado
  (`acceptance_paired_ablation` em `phase4_evaluate.py`) substitui o antigo
  max-sobre-baselines; resta apenas EXECUTAR (Passos 6/8/9) para emitir o verdict.
- **REQ:** REQ-MOD-3, REQ-MET-4 (emenda v1.1), REQ-AUD-2 (emenda v1.1), REQ-MOD-6,
  design 4.5.2.1, 21.3, 21.7, 28.6, 29.4, 29.5.

---

## Fase 5 - Calibracao + confidence audit

### T-5-1: Conformal por CP
- [ ] `core/calibration/conformal.py`: por `cp_utc`. Janela 60-90 dias auditada.
- [ ] Cross-check com janela sazonal de 12 meses.
- **Done:** IC80 com cobertura empirica `0.80 +/- 0.04`.
- **REQ:** REQ-MOD-4, REQ-AUD-2.

### T-5-2: Conformal por bucket (opcional)
- [ ] Bucketing por `(month, regime, cp)` com `n_min=200`.
- **Done:** ablation contra bucketless conformal.
- **REQ:** REQ-MOD-4.

### T-5-3: Heteroscedasticidade test
- [ ] Bins por quartis de largura do IC; cobertura empirica por bin.
- [ ] Falha se algum bin viola `(0.80 - 0.10, 0.80 + 0.10)` enquanto outro esta dentro.
- **Done:** test passa.
- **REQ:** REQ-AUD-5.

### T-5-4: Confidence score implementacao
- [ ] `core/confidence/score.py`: combinador conforme design 8.3.
- [ ] Fit de pesos `w` via logistic regression contra `bracket_correct` no train split + isotonic regression para calibracao final.
- **Done:** scores entre 0 e 1; ECE <= 0.05 em hold-out.
- **REQ:** REQ-CONF-1, REQ-CONF-2.

### T-5-5: Auditoria do confidence
- [ ] Emitir `audits/<run_id>/confidence_audit.json`:
  - `ECE`,
  - tabela `bracket_match @ coverage in {25%, 50%, 75%, 100%}`.
- **Done:** auditoria parte do `audit` CLI.
- **REQ:** REQ-CONF-1, REQ-MET-2.

### T-5-6: Stay-out logic
- [x] Adicionar `min_confidence` em `nzwn/config/model.yaml`.
- [x] Decision engine retorna `NO_TRADE("low_confidence")` se score abaixo do limiar.
- **Done:** comportamento testado em integration test.
- **PHASE 5 CLOSED NOT READY (2026-05-30, stop criterion B3):** REQ-AUD-5 het gate never
  passed (v1.0/A1/A3/P/P'/D1/S). Stay-out is DISABLED in production
  (`confidence.gate_enabled_in_production: false`; `production_confidence_gate` no-ops when
  off) and kept DIAGNOSTIC only. See `reports/phase5_closure.md`. Roadmap advances to
  late-spike + shadow/EV.
- **REQ:** REQ-CONF-3.

---

## Fase 6 - AR online (opcional)

### T-6-1: AR(7) residual
- [x] `core/online/ar.py::AROnlineCorrector` com estado em json.
- [x] Garantir que update so usa `truth(D-1)` apos `postmortem` rodar (estritamente passado).
- **Done:** unit test cobre updates sequenciais sem leakage (`tests/unit/test_ar_online.py`).
- **REQ:** REQ-MOD-5.

### T-6-2: Backup e dedupe
- [x] Backup `<date>.bak.json` antes de cada update.
- [x] Rejeitar updates duplicados pelo mesmo `(date_local, cp_utc)`.
- **Done:** integration test cobre tentativa duplicada (`tests/unit/test_ar_online.py`).
- **REQ:** REQ-OPS-5.

### T-6-3: DM-test
- [ ] Comparar AR-on vs AR-off vs persistencia. (BLOCKED: consome predicoes da Fase 5 em andamento.)
- [ ] Publicar em `reports/ar/<run_id>.md`.
- **Done:** AR melhora em >= 2/3 splits ou flag desabilitada.
- **REQ:** REQ-MOD-5, REQ-MET-3.

### T-6-4: Feature flag
- [x] `nzwn/config/model.yaml`: `ar_online.enabled: false` por default.
- **Done:** habilitar/desabilitar sem redeploy de codigo.
- **REQ:** REQ-MOD-5.

---

## Fase 7 - Late spike

### T-7-1: Labels L1
- [x] `core/spike/labels.py`: `late_spike_l1` (REQ-SPK-1) ja parcialmente em T-1-5; reusar e estender para todos os CPs avaliados.
- **Done:** label `late_spike_l1__cp_HH` (k_eod != k_cp) ja emitido por `core/labels/tmax.py` para todo CP_SET; consumido pelo spike evaluator.
- **REQ:** REQ-SPK-1.

### T-7-2: Features de spike
- [x] `core/spike/features.py`: time_since_new_max, slopes, mudanca de regime, vis/ceiling, pos-chuva, NWP disagreement.
- **Done:** 14 features causais em `SPIKE_FEATURE_COLUMNS` com guard `ts_utc < cp_utc` (REQ-AUD-4); regime/NWP opcionais (None ate Fase 7 GMM).
- **REQ:** REQ-SPK-2.

### T-7-3: Modelo LightGBM binario
- [x] `core/spike/model.py`: train + isotonic regression.
- [x] Seeds fixas.
- **Done:** LightGBM binario + IsotonicRegression (seed 42); `fit_spike_model`/`predict_spike_risk`. REQ-SPK-3 PASS 3/3 (PR-AUC 0.947/0.948/0.953 vs prevalencia 0.81/0.85/0.81; bootstrap CI95 lower bound > prevalencia em todos os splits).
- **REQ:** REQ-SPK-3.

### T-7-4: Auditoria de timestamps
- [x] Frozen observation test cobre as features do spike.
- **Done:** no-leak test em `tests/unit/test_spike_features.py` (features inalteradas ao anexar obs pos-cp).
- **REQ:** REQ-SPK-2, REQ-AUD-4.

### T-7-5: Integracao em confidence e decision
- [x] `confidence_score` recebe `-spike_risk` no agregado.
- [x] Decision engine implementa `BLOCK_BUY_NO_LATE_SPIKE` quando `spike_risk >= threshold_spike`.
- **Done:** `neg_spike_risk` e o 6o phi em `core/confidence/score.py` (opcional/None backward-compat); `decide()` em `core/decision/engine.py` cobre todos os estados (`tests/unit/test_decision_engine_full.py`).
- **REQ:** REQ-CONF-2, REQ-DEC-2.

### T-7-6: Reportar metricas obrigatorias
- [x] `reports/spike/<run_id>.md` com PR-AUC, recall@FPR<=0.05, ECE.
- **Done:** emitido por `scripts/spike_evaluate.py` (walk-forward 2023/2024/2025 + bootstrap CI95).
- **REQ:** REQ-SPK-3.

---

## Fase 8 - Shadow trading + EV

### T-8-0: Definir conjunto de mercados v1 e congelar `EXECUTION_VERSION`
- [ ] Listar `eventUrl` dos mercados Polymarket v1 a serem auditados/shadow-tradados (provavelmente "Tmax NZWN >= k" para alguns brackets, OU equivalente disponivel). (BLOCKED: precisa de eventUrls reais do Polymarket.)
- [ ] Gravar lista em `nzwn/config/markets.yaml` com `market_id`, `eventUrl`, `bracket_type`, `granularity`. (BLOCKED: idem.)
- [x] Criar `contracts/execution.md` com `EXECUTION_VERSION=1.0` cobrindo todos os parametros de REQ-MET-5 (defaults v1: `fee_bps=200`, `slippage=taker_at_quote`, `entry=ask`, `fill=assume_full_fill`, `sizing=1 unit`, `max_concurrent=1/cp`, `tif=cancel_at_next_cp`).
- [x] Pydantic validator em `core/contracts/execution.py`.
- **Done (parcial):** contrato `EXECUTION_VERSION=1.0` + pydantic `ExecutionContract` validados; `markets.yaml`/eventUrls aguardam dados reais do Polymarket (T-8-1/8-2 seguem BLOCKED).
- **REQ:** REQ-MET-5, REQ-DEC-4.

### T-8-1: Resolver audit (OPN-1) - LIVE/manual, not a 30-day miner
- **SCOPE CORRECTED (2026-05-30):** no historical odds dataset. The resolver check is a
  LIGHT live/manual confirmation that Polymarket's published integer == `Q(decimal)` for NZWN,
  done when live markets exist - NOT a 30-day historical mining job.
- [ ] Live spot-check `decimal -> Q(decimal)` vs published integer when a market is open.
- **Done:** `contracts/resolver.md` promoted to v1.0 after the live confirmation.
- **REQ:** REQ-CON-2.

### T-8-2: Live odds snapshot (at the forecast CP) - REPLACES historical ingestor
- **SCOPE CORRECTED (2026-05-30):** odds are captured ONLY at the live forecast CP for EV/Kelly
  context (REQ-DEC-4); there is no historical odds ingestion/backfill.
- [x] `core/ingest/odds.py`: `event_slug`/`event_url` (deterministic pattern), `snapshot_live(city, d, cp_utc)`
  -> `OddsSnapshot` (brackets as `ContractRange` + YES/NO prices + SHA256) via Gamma API.
- [x] `core/decision/sizing.py::size_book` maps the model `prob_dist` over a live snapshot to
  per-bracket EV/Kelly (the forecast -> odds -> sizing path).
- **Done:** offline parse/slug tests (`tests/unit/test_odds_ingest.py`, 4) + live end-to-end
  verified against `highest-temperature-in-wellington-on-may-31-2026` (11 brackets). Bracket->range
  + URL pattern documented in `contracts/resolver.md`.
- **REQ:** REQ-DEC-4.

### T-8-3: Decision engine completo
- [x] `core/decision/engine.py` conforme design 10.
- [x] Tres estados operacionais (REQ-DEC-2).
- [x] `expected_value` computado.
- **Done:** `decide()` cobre NO_TRADE(low_confidence)/BLOCK_BUY_NO_LATE_SPIKE/NO_TRADE_RESOLVED/OPPORTUNITY_ASSYMETRIC/BUY_NO/NO_TRADE(no_edge) com edges via `market_map.p_yes`; `EngineDecision` carrega edge_yes/edge_no/p_yes; `tests/unit/test_decision_engine_full.py` cobre cada estado.
- **REQ:** REQ-DEC-1, REQ-DEC-2.

### T-8-4: Threshold tuning - nested walk-forward (OFFLINE, odds-free objective)
- **SCOPE CORRECTED (2026-05-30):** tuning uses the ODDS-FREE objective
  `max(bracket_match_when_traded) s.t. coverage` (contracts/objective.md). EV/Sharpe objectives
  are live-only and are NOT tuned offline.
- **BLOCKED UNTIL:** decided to tune (optional; model already promoted by forecast-quality).
- [ ] `core/decision/threshold_tuning.py`: nested walk-forward (REQ-MET-6), TEST evaluated once.
- [ ] Hard rules: only `min_edge_*`, `no_too_expensive`, `min_confidence`, `spike_block` tunable;
  `tau`/`safety_margin`/model hyperparams forbidden.
- **REQ:** REQ-DEC-3, REQ-MET-6.

### T-8-5: ~~Backtest de execucao~~ REMOVED (no historical odds)
- **REMOVED (2026-05-30):** an equity-curve backtest requires historical odds, which do not
  exist. `shadow_simulate` stays as a SINGLE-trade PnL/what-if tool for an already-resolved live
  forecast (postmortem), not a historical equity backtest. No `equity_curve.parquet`.
- **REQ:** (n/a)

### T-8-6: ~~economic_edge forensic phase~~ DEFERRED to live
- **DEFERRED (2026-05-30):** EV-expected-vs-realized needs live trades over time; it cannot run
  offline without odds. `audits/phases/rest.py::economic_edge` stays `passed=None` (live-only).
- **REQ:** REQ-AUD-1, REQ-MET-1.

### T-8-9: Live EV + Kelly sizing - NEW (the actual live-odds capability)
- [x] `core/decision/sizing.py`: `expected_value(p, price, fee_bps)`, `kelly_fraction(p, price, kelly_cap)`,
  `size_side(side, p_yes, price, contract)` from the model `prob_dist` (via `market_map.p_yes`) +
  the live odds snapshot.
- [x] `ExecutionContract` gains `position_sizing='fractional_kelly'` + `kelly_cap`.
- **Done:** `tests/unit/test_sizing.py` (9): EV sign/fee, Kelly cap/floor/monotonicity, BUY_NO
  complement, flat vs Kelly sizing. EV/Kelly are computed AT the live CP only.
- **REQ:** REQ-MET-5, REQ-DEC-4.

### T-8-7: Shadow execution simulator
- **BLOCKED UNTIL:** T-8-0 (`contracts/execution.md` v1.0).
- [x] `core/decision/shadow_exec.py` implementa o pseudocodigo de design 10.1 lendo `contracts/execution.md`.
- [x] Suporta switches `assume_full_fill` (default v1) e `partial_fill_with_min_size` (ablation em `experiments/`).
- [x] Test unit sobre cenarios: fill completo, sem fill, fee cobrada, payoff resolvido em favor.
- **Done:** `shadow_simulate(decision, market, exec_contract, truth)` deterministico; `tests/unit/test_shadow_exec.py` (10). CI guard de backtest sem `EXECUTION_VERSION` fica para T-8-5.
- **REQ:** REQ-MET-5.

### T-8-8: Market map (prob_dist -> p_yes por contract)
- [x] `core/decision/market_map.py`:
  - `p_yes(contract_range) = sum(prob_dist[k] for k in support_K if k_lo <= k <= k_hi)`,
  - validador `assert sum(p_yes(c)) <= 1 + 0.02` em snapshots de odds.
- [x] Test unit cobre: contract `=k`, contract `[a,b]`, contract aberto `>=k`.
- **Done:** `p_yes` + `assert_p_yes_normalized` expostos e consumidos por `decision.engine.decide`; `tests/unit/test_market_map.py` (8) cobre =k/[a,b]/>=k/<=k + normalizacao.
- **REQ:** REQ-DEC-1, design 10.

---

## Fase 9 - Melhoria do preditor (FOCO ATUAL, 2026-05-31)

> O core vence baselines (REQ-MET-4 PASS). Esta fase MELHORA o sinal do preditor de Tmax. Gate
> de cada arm: ganho de MAE/bracket-match (ou RPS) walk-forward >= 2/3 splits, IC/sem-leak, SEM
> afrouxar gate, SEM tocar execucao. Cada arm tem prereg + relatorio (rotina). Promove o que
> passa; mata honestamente o que nao passa.

### T-9-1: analog_high_risk_arm_v0 (lado high-risk / late-warming)
- [x] Construir o arm de analogos (retrieval ja validado: `analog_retrieval_audit` g1-g4 PASS;
  `analog_quality_v0.1` resolve g5 via `analog_confidence`). Blendar `P_analog` com o Ridge
  SOMENTE em dias non-calm (calm_day_filter=false), ponderado por `analog_confidence`.
- [x] Medir MAE/bracket-match/RPS walk-forward 2023/24/25, ESPECIALMENTE em dias de late-warming
  e non-calm, vs Ridge puro.
- **Done:** **GO** (prereg `contracts/analog_high_risk_arm_v0_prereg.md`; pipeline de 3 agentes:
  prereg meu + impl/review subagentes + re-verificacao minha). Gate ex-ante (predicted_risk>=c30),
  NAO truth-derived. Non-calm MAE 3/3 melhora (0.727->0.704/0.718->0.704/0.700->0.693), BM 2/3,
  agregado nao degrada. Anti-leak review 10/10. **Caveat honesto: ganho REAL mas PEQUENO** (blend
  conservador); o buraco maior e a distribuicao/intervalo (T-9-3). `reports/analog/analog_high_risk_arm_v0.md`.
- **REQ:** REQ-MOD-1, REQ-MET-3, REQ-MET-4.

### T-9-2: calm_day suppression (lado low-risk)
- [ ] Usar `calm_day_filter_v0` (GO=True) para suprimir overcorrection: em dias calmos, confiar
  mais em Ridge/persistencia e/ou estreitar a distribuicao.
- [ ] Medir se estreitar em dias calmos melhora RPS sem perder coverage.
- **Done:** ganho de RPS/coverage walk-forward >= 2/3 ou kill honesto. `reports/...`.
- **REQ:** REQ-MOD-1, REQ-MET-3.

### T-9-3: distribuicao calibravel condicional (o "telhado")
- [x] Atacar o problema aberto da Fase 5: cobertura CONDICIONAL (heteroscedastica). Sem isto a
  distribuicao para brackets e fraca mesmo com ponto forte.
- [x] Explorar conformal condicional por regime calm/high-risk (os dois estratos agora existem).
- **Done:** **KILL honesto** (prereg `contracts/conditional_calibration_v0_prereg.md`; pipeline de 3
  agentes + re-verificacao minha). Conformal condicional por regime EX-ANTE (calm/non_calm via risco
  previsto, c30=train P30) NAO conserta a over-coverage estrutural: G1 cobertura global fora de
  [0.78,0.86] (0.93/0.91/0.91), G2 het-gate + per-regime fora de banda (calm 0.945, non_calm 0.904 -
  AMBOS over-cover), G3 sem inflacao de largura. A folga e GLOBAL+estrutural (Q-apos-decimal +
  rank finito), nao isolavel por regime. CONFIRMA o closure da Fase 5. Het gate reusado sem afrouxar.
  **Telhado continua aberto.** Proximo candidato: NWP-spread sigma OU aceitar ridge_conformal_minimal
  como stopgap operacional. `reports/calibration/conditional_calibration_v0.md`.
- **REQ:** REQ-MOD-4, REQ-AUD-5, REQ-CONF-1.

### T-9-4: NWP em leads mais cedo (so apos 9-1..9-3)
- [ ] Explorar o ganho NWP em 20-22Z (Phase 4 mostrou ser onde o ganho e maior).
- **Done:** ganho walk-forward por CP >= 2/3 ou kill. `reports/...`.
- **REQ:** REQ-MOD-3, REQ-MET-3.

### T-9-5: native_integer_conformal_v0 (atacar o objeto de calibracao)
- [x] Calibrar nativamente no inteiro (M1 |residuo| simetrico; M2 residuo signed), SEM decimal->Q.
- **Done:** **KILL DECISIVO** (prereg `contracts/native_integer_conformal_v0_prereg.md`; pipeline 3
  agentes + re-verificacao minha). Nativo-inteiro AINDA over-covers (het FAIL >=2/3) -> **refuta a
  hipotese Q-apos-decimal**: a folga e a GRANULARIDADE inteira em si. M2 e estritamente mais estreito
  que v1.0 3/3 (4.25/4.00/3.75 vs 4.27/4.28/3.77), mas nao bate het em 2/3. het gate reusado sem
  afrouxar. `reports/calibration/native_integer_conformal_v0.md`.
- **REQ:** REQ-MOD-4, REQ-AUD-5.

### T-9-6: nwp_spread_sigma feasibility (proximo eixo fisico)
- [x] Feasibility-first: existe nwp_spread causal no CP com qualidade para rastrear |erro_int|?
- **Done:** **NOT FEASIBLE** (`scripts/evaluate_nwp_spread_sigma.py`). Arquivo local tem so 1 modelo
  (NCEP GFS) -> spread/disagreement identicamente zero. Revisitar exige 2a fonte NWP causal (ECMWF).
  `reports/calibration/nwp_spread_sigma_feasibility.md`.
- **REQ:** REQ-MOD-4, REQ-DAT-5.

### T-9-7: calibration_stopgap_decision (memo operacional)
- [x] Formalizar o que pode ser usado enquanto o telhado segue aberto.
- **Done:** `docs/decisions/calibration_stopgap_2026-05-31.md` - `ridge_conformal_minimal` como
  DIAGNOSTICO-only (over-covers 0.86-0.91), nunca gate de trade (`gate_enabled_in_production: false`
  permanece), banner obrigatorio, aposentado quando algo passar REQ-AUD-5 >=2/3.
- **REQ:** REQ-CONF-1, REQ-CONF-3.

> **Conclusao estrategica de calibracao (2026-05-31):** um IC80 INTEIRO calibrado provavelmente NAO e
> recuperavel com o modelo de ponto + granularidade atuais. Tres ataques independentes (regime T-9-3,
> objeto nativo-inteiro T-9-5, eixo NWP-spread T-9-6) falharam/inviaveis. Calibracao = SETTLED-WITH-
> STOPGAP; unico lever restante = 2a fonte NWP causal (revisitar T-9-6). Nao repetir Mondrian por mais
> eixos locais sem nova hipotese forte.

---

## Tasks transversais (qualquer momento)

### T-X-1: Documentacao no README
- [ ] `README.md` na raiz aponta para `.kiro/specs/polymarket-tmax-forecaster/` e descreve setup local, comandos principais e link para v1 historico.
- **REQ:** REQ-SEC-3 (atribuicao IEM ASOS).

### T-X-2: Atualizar contratos quando mudarem
- [x] CI guard: contrato sem declaracao de versao falha o build.
- **Done:** `tools/contract_version_guard.py` (`contracts_missing_version`/`main`); 14 contratos passam; `tests/integration/test_contract_version_guard.py`. (Metade git-diff "mudou sem bump" fica para CI com historico.)
- **REQ:** REQ-CON-1.

### T-X-3: Postmortem mensal
- [x] Script que sumariza ultimos 30 dias: bracket-match, ECE, drift de regime. EV = n/a (live-only, sem odds historicas).
- **Done:** `scripts/postmortem_monthly.py::summarize` + `main` -> `reports/postmortem/<YYYY-MM>.{md,json}`; `tests/unit/test_postmortem_monthly.py`.
- **REQ:** REQ-OPS-4 (extensao).

### T-X-4: Cleanup de scratch
- [ ] Job mensal limpa `artifacts/scratch/` mantendo somente arquivos referenciados em PRs abertos.
- **REQ:** REQ-REP-4.

---

## Mapa REQ -> tasks (rastreabilidade)

| REQ | Tasks |
|-----|-------|
| REQ-CON-1 | T-0-3, T-X-2 |
| REQ-CON-2 | T-0-7 (v0.1, OPN-1a), T-8-1 (v1.0, OPN-1) |
| REQ-CON-3 | T-1-1, T-1-4, T-1-5, T-1-11 |
| REQ-CON-4 | T-0-4, T-1-3, T-1-5 |
| REQ-CON-5 | T-1-6 |
| REQ-CON-6 | T-0-4, T-0-7 |
| REQ-CON-7 | T-1-10, T-1-8 |
| REQ-CON-8 | T-1-11 |
| REQ-DAT-1 | T-1-2 |
| REQ-DAT-2 | T-1-6 |
| REQ-DAT-3 | T-0-3, T-1-1, T-1-4 |
| REQ-DAT-4 | T-2b-1, T-2b-2, T-2b-3 |
| REQ-DAT-5 | T-4-2 (NWP selection v1 inclusa) |
| REQ-MOD-1 | T-2-1, T-3-2, T-4-4 |
| REQ-MOD-2 | T-3-1, T-3-2 |
| REQ-MOD-3 | T-4-3, T-4-4 |
| REQ-MOD-4 | T-5-1, T-5-2 |
| REQ-MOD-5 | T-6-1, T-6-3, T-6-4 |
| REQ-MOD-6 | T-0-4, T-3-7, T-4-4, T-7-3 |
| REQ-CONF-1 | T-5-4, T-5-5 |
| REQ-CONF-2 | T-2b-4, T-5-4, T-7-5 |
| REQ-CONF-3 | T-5-6 |
| REQ-DEC-1 | T-8-3, T-8-8 |
| REQ-DEC-2 | T-7-5, T-8-3 |
| REQ-DEC-3 | T-0-3, T-8-4 |
| REQ-DEC-4 | T-8-0, T-8-2 |
| REQ-SPK-1 | T-1-5, T-7-1 |
| REQ-SPK-2 | T-7-2, T-7-4 |
| REQ-SPK-3 | T-7-3, T-7-6 |
| REQ-AUD-1 | T-2-3, T-8-6 |
| REQ-AUD-2 | T-3-4, T-3-5, T-3-8, T-5-1 |
| REQ-AUD-3 | T-0-5, T-2-4 |
| REQ-AUD-4 | T-1-6, T-7-4 |
| REQ-AUD-5 | T-5-3 |
| REQ-AUD-6 | T-3-8 |
| REQ-OPS-1 | T-0-6, T-2-1 |
| REQ-OPS-2 | T-0-5, T-0-6 |
| REQ-OPS-3 | T-0-6, T-2-5 |
| REQ-OPS-4 | T-2-2, T-X-3 |
| REQ-OPS-5 | T-6-2 |
| REQ-REP-1 | T-0-1 |
| REQ-REP-2 | T-1-9 |
| REQ-REP-3 | T-0-5 |
| REQ-REP-4 | T-X-4 |
| REQ-MET-1 | T-8-5, T-8-6 |
| REQ-MET-2 | T-1-8, T-1-10, T-2-2, T-5-5 |
| REQ-MET-3 | T-1-7, T-3-3, T-4-5, T-6-3 |
| REQ-MET-4 | gate de Fase 3 (T-3-4) |
| REQ-MET-5 | T-8-0, T-8-7, T-8-5 |
| REQ-MET-6 | T-8-4 |
| REQ-SEC-1 | (config gerencial; sem task de codigo) |
| REQ-SEC-2 | T-0-2 |
| REQ-SEC-3 | T-0-1, T-X-1 |
| OPN-1a | T-0-7 |
| OPN-1 | T-8-1 |
| OPN-3 | T-8-4 |
| OPN-5 | T-4-1 (closed) |
| OPN-5a | T-OPN-5a |

---

## Definition of Done global

Uma fase e considerada "concluida" quando:

1. Todas as tasks marcadas `[x]`.
2. Todos os gates pre-registrados passam (REQ-AUD-2 e gates da fase).
3. Auditoria forense roda e emite `h0_verdict.json` valido.
4. CI verde com determinism check ativo.
5. Relatorio comparativo publicado em `reports/`.
6. Tabela `bracket_match @ coverage` presente nos relatorios da fase.
7. Sem violacao de timestamp em qualquer feature do dataset.

Tasks adicionadas durante a execucao devem referenciar o `REQ-*` que motivam, ou ser registradas como scope creep e rejeitadas.
