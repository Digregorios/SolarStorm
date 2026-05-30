# Requirements - Polymarket Tmax Forecaster (NZWN)

> **Spec version:** 1.0  
> **Idioma:** PT-BR (ASCII em logs, paths e CLIs - ver REQ-OPS-2)  
> **Estilo:** EARS (Easy Approach to Requirements Syntax) - "WHEN <gatilho> THEN o sistema SHALL <comportamento>".  
> **Origem:** Refinamento do `Polymarket Tmax Forecaster - Design & Specs (v1)` + auditoria de `NZWN.csv` (112.190 linhas, 2020-01-01 a 2026-05-27, cadencia 30 min).  
> **Escopo:** intraday D0 para Tmax(NZWN) inteiro em °C, com forecast por checkpoint (CP), confianca calibrada, modulo de late spike e auditoria forense anti-nowcaster.

---

## 0. Glossario operacional

- **CP (checkpoint):** instante (em UTC) no qual uma previsao e emitida para o dia local D0.
- **CP operacional padrao (NZWN):** `23:00 UTC` (~11:00 local Pacific/Auckland), conforme decisao registrada na secao 21.1 do v1.
- **Tmax(D0):** valor inteiro de temperatura maxima em °C resolvido pelo METAR no dia local D0 (00:00-23:59 local).
- **B(k):** banda inversa do inteiro `k`. Default: `B(k) = [k - 0.5, k + 0.5)`.
- **Q(x):** funcao de quantizacao oficial. Default: `Q(x) = floor(x + 0.5)` (round-half-up).
- **Bracket:** intervalo de Tmax inteiro publicado pelo mercado Polymarket (pode ser `=k`, `<=k`, `[k1,k2]` etc.).
- **NWP:** Numerical Weather Prediction (forecast, **nao** reanalysis/archive).
- **Nowcaster:** modelo que apenas reage a temperatura observada recente (anti-padrao).
- **Late spike:** revisao tardia do Tmax apos o CP operacional que cruza para outro inteiro/bracket.
- **Resolver:** entidade que decide a resolucao oficial do mercado (Polymarket).

---

## 1. Contratos de dados e verdade

### REQ-CON-1: Quantizacao oficial (default congelado)
WHEN o sistema gerar labels, treinar, avaliar ou reportar resultados,
THEN ele SHALL usar `B(k) = [k - 0.5, k + 0.5)` e `Q(x) = floor(x + 0.5)` como definicao oficial,
AND SHALL versionar este contrato em `contracts/quantization.md` com identificador `Q_VERSION`.

### REQ-CON-2: Validacao do contrato com o resolver Polymarket
WHEN o pipeline for promovido para Fase 8 (shadow trading),
THEN o sistema SHALL ter um documento `contracts/resolver.md` que registre:
estacao/ICAO (`NZWN`), feed-fonte de verdade, janela do dia local, timezone, tratamento de METAR ausente e SPECI,
AND SHALL conter um relatorio quantitativo (`reports/resolver_audit.md`) comparando >= 30 dias de decimais vs inteiro publicado para inferir Q efetivo do mercado,
AND SHALL bloquear deploy se Q efetivo divergir do default em mais de 1% dos dias auditados sem documentar a divergencia.

### REQ-CON-3: Verdade observacional inteira
WHEN o sistema computar `k_obs` (Tmax inteiro publicado),
THEN ele SHALL extrair a temperatura **inteira em °C** do campo `metar` cru (ex.: `19/14`) e nao do campo decimal `tmpf` convertido,
AND SHALL fazer cross-check entre `Q(round((tmpf - 32) * 5/9))` e o inteiro do METAR, registrando divergencias no relatorio de qualidade.

### REQ-CON-4: Janela do dia local e DST
WHEN o sistema definir `D0` ou agregar Tmax/Tmin diarios,
THEN ele SHALL usar `zoneinfo.ZoneInfo("Pacific/Auckland")` para mapear UTC -> local,
AND SHALL cobrir 24h completas do dia local (00:00:00 - 23:59:59),
AND SHALL ter testes unitarios cobrindo as duas transicoes anuais de DST (inicio e fim).

### REQ-CON-5: Causalidade estrita por CP
WHEN o sistema calcular qualquer feature ou previsao para um CP `t`,
THEN nenhuma feature SHALL usar dados com timestamp `> t`,
AND janelas rolling SHALL ser estritamente passadas (equivalente a `closed='left'`),
AND o sistema SHALL falhar com erro explicito (nao silencioso) se detectar uso de dado futuro em modo treino ou inferencia.

### REQ-CON-6: CP set oficial (congelado)
WHEN o sistema avaliar, treinar ou emitir relatorios,
THEN ele SHALL usar **exatamente** o conjunto oficial de checkpoints definido em `nzwn/config/station.yaml`:
`CP_SET = [20:00, 21:00, 22:00, 23:00] UTC` (default v1; CP operacional = `23:00 UTC`),
AND um "CP" SHALL sempre ser um inteiro de hora UTC no formato `HH:00:00`,
AND tabelas de metricas, gates, snapshots de odds e auditoria forense SHALL ser computados para **todos** os CPs do `CP_SET`,
AND adicionar/remover CPs SHALL exigir bump de `Q_VERSION` (ou versao equivalente do contrato `station.yaml`) e re-execucao da auditoria forense (REQ-AUD-1).

> **Anti-padrao explicitamente proibido:** introduzir CPs ad-hoc para reportar a metrica que melhor performou.

### REQ-CON-7: Day completeness (regra objetiva e auditavel)
WHEN o sistema decidir se um dia local D0 e usavel para treino/avaliacao,
THEN ele SHALL marcar `day_complete = True` se e somente se **todas** as condicoes a seguir forem verdadeiras:
- `n_obs >= 40` em 24h locais (cadencia nominal IEM e 30 min -> ate 48 obs/dia; 40 absorve gaps moderados),
- `max_gap_minutes <= 120` (sem buracos > 2h consecutivas),
- existe pelo menos `1` observacao em **cada** quartil do dia local: `[00:00, 06:00)`, `[06:00, 12:00)`, `[12:00, 18:00)`, `[18:00, 24:00)`,
AND dias com `day_complete = False` SHALL ser excluidos de treino e do calculo de metricas-alvo (mas SHALL aparecer em relatorios de cobertura),
AND a taxa de `day_complete = False` SHALL ser monitorada por mes (REQ-MET-2).

> **Justificativa:** evita p-hacking ("descartar dias dificeis") e bugs silenciosos em labels.

### REQ-CON-8: Fallback policy para extracao de Tmax inteiro
WHEN o regex de extracao de inteiro do `metar` cru (REQ-CON-3) falhar,
THEN o sistema SHALL aplicar fallback **apenas** se o `metar` cru estiver ausente ou ilegivel (vazio, malformado),
AND o fallback `Q(round((tmpf - 32) * 5/9))` SHALL ser usado a partir de `tmpf` decimal,
AND `data_quality.tmp_c_int = "imputed"` SHALL ser propagado para a observacao,
AND o sistema **NAO** SHALL aplicar fallback quando o regex casa parcialmente ou retorna valor improvavel - nesses casos a observacao SHALL ser marcada `data_quality.tmp_c_int = "missing"` e ignorada,
AND o relatorio de auditoria SHALL incluir `fallback_rate_per_month` em `reports/eda/decimal_vs_int_check.md`,
AND **kill criterion**: se `fallback_rate_global > 0.5%` no historico, parar e revisar parser/fonte antes de avancar para Fase 2.

---

## 2. Ingestao e snapshots

### REQ-DAT-1: Snapshot deterministico do METAR cru
WHEN o sistema ingerir METAR (do CSV historico ou de feed em runtime),
THEN ele SHALL salvar um snapshot bit-for-bit em `artifacts/raw/metar/<station>/<yyyy>/<mm>/<dd>.csv` (ou `.txt` por mensagem),
AND SHALL gravar `SHA256` do snapshot em `artifacts/raw/metar/manifest.jsonl`,
AND reprocessamentos SHALL partir do snapshot, nao do feed (feeds podem revisar retroativamente).

### REQ-DAT-2: Dataset derivado CP-aware
WHEN o builder de dataset gerar features para treino/inferencia,
THEN ele SHALL produzir, para cada par `(date_local, cp_utc)`, uma linha com:
- features causais (todas com `feature_max_ts <= cp_utc`),
- baselines (persistencia, climatologia smoothed, NWP cru se disponivel),
- `data_quality` (flag por feature: `ok | imputed | missing`),
- `dataset_version` e SHA256 do snapshot de origem.

### REQ-DAT-3: Tratamento de "M" (missing) do IEM
WHEN o sistema ler `NZWN.csv` e encontrar valor `M` em qualquer coluna,
THEN ele SHALL converter para `NaN` e propagar a flag para `data_quality`,
AND nao SHALL silenciar o missing por imputacao default; imputacao requer regra explicita por feature, documentada em `contracts/imputation.md`.

### REQ-DAT-4: TAF como input exogeno (opcional, Fase 2+)
WHEN o sistema usar TAF,
THEN ele SHALL salvar snapshot bruto + SHA256 igual ao METAR,
AND SHALL parsear em segmentos com (`issued_time_utc`, `valid_from_utc`, `valid_to_utc`, `station`),
AND em qualquer CP `t`, SHALL usar apenas TAFs com `issued_time_utc <= t`,
AND SHALL ser rejeitado em backtest qualquer TAF emitido apos o CP.

### REQ-DAT-5: NWP forecast (nao archive)
WHEN o sistema usar NWP,
THEN ele SHALL usar somente `historical-forecast` (run + lead disponiveis no CP),
AND SHALL salvar `(model, run_time_utc, lead_hours, valid_time_utc)` por snapshot,
AND SHALL falhar o build se detectar uso de reanalysis/archive como se fosse forecast,
AND **cada snapshot NWP SHALL persistir `run_time_utc` (issued_time)** explicito (reforco A do open-meteo brainstorm),
AND o ingest builder SHALL validar `run_time_utc <= cp_utc - safety_margin` (reforco B) - violacao = `RuntimeError`,
AND o `Frozen observation test` (audit phase 2) SHALL ter check dedicado para NWP rows
(rejeita rows com `run_time_utc > cp_utc - safety_margin` mesmo se acidentalmente ingeridas),
AND `safety_margin` SHALL viver em `nzwn/config/model.yaml::nwp.safety_margin_minutes`
(default v1 = 60 min, registrado por `NWP_SOURCE_VERSION`).

> **Nota empirica (Open-Meteo Historical Forecast API):** o stitching das primeiras
> horas de cada run pode introduzir leakage de assimilacao de ate ~3h. A criterio
> de aceitacao definitivo da fonte vem da task **OPN-5a** (HFAPI vs Single Runs cross-check).

---

## 3. Modelo e previsao (core)

### REQ-MOD-1: Saidas minimas por CP
WHEN o core emitir uma previsao para `(date_local, cp_utc)`,
THEN ele SHALL produzir:
- distribuicao discreta `P(Tmax = k)` para um conjunto de inteiros candidatos,
- `P50_k` (mediana inteira) e `IC80` no espaco inteiro,
- `confidence_score` calibrado,
- `spike_risk` (se Fase 7+),
- `forecast_id`, hashes de artefatos de modelo, `dataset_version`, `data_quality`, `cp_utc`, `cp_local`, `tz_name`.

### REQ-MOD-2: Loss band-aware no treino
WHEN o sistema treinar modelo continuo (Ridge, GBM etc.),
THEN ele SHALL usar loss compativel com B(k):
erro `0` se `y_hat in B(k_truth)`, penalidade fora da banda (linear ou quadratica como ablation),
AND SHALL reportar a variante usada em metadata do modelo.

### REQ-MOD-3: NWP residual learning como abordagem preferida
WHEN o sistema atingir Fase 4+,
THEN o core SHALL ser estruturado como `prediction = NWP_baseline + correction(features_causais)`,
AND blend convexo `beta * NWP + (1-beta) * ML` SHALL existir apenas como baseline/controle, nao como producao do core.

### REQ-MOD-4: Calibracao conformal por CP
WHEN o sistema gerar IC,
THEN ele SHALL usar conformal por CP (e opcionalmente por bucket com `n_min` documentado),
AND cobertura empirica do IC80 SHALL estar em `0.80 +/- 0.04` no test split.

### REQ-MOD-5: AR online (Fase 6, opcional)
WHEN o sistema for promover correcao online (AR(7) residual ou similar),
THEN ele SHALL:
- ser estritamente passado (sem leakage),
- gravar backup do estado antes de cada update,
- ter feature-flag `ar_online.enabled` desligavel sem redeploy,
- passar DM-test/walk-forward vs persistencia em >= 2/3 splits.

### REQ-MOD-6: Determinismo de treino
WHEN o sistema treinar um modelo,
THEN ele SHALL fixar seeds em: `random`, `numpy`, e RNGs especificos da biblioteca (ex.: LightGBM `seed`, `bagging_seed`, `feature_fraction_seed`),
AND `CI` SHALL rodar dois treinos consecutivos com mesma config/dados e validar SHA256 igual do artefato (ou criterio de tolerancia explicito documentado).

---

## 4. Confianca (selective forecasting)

### REQ-CONF-1: Confidence score calibrado
WHEN o sistema emitir `confidence_score`,
THEN ele SHALL estar calibrado contra `P(bracket_correct)` em hold-out temporal,
AND SHALL ter ECE <= 0.05 reportado em `audits/<run_id>/confidence_audit.json`,
AND SHALL ter tabela obrigatoria de `bracket_match @ coverage in {25%, 50%, 75%, 100%}`.

### REQ-CONF-2: Sinais minimos do confidence
WHEN o sistema computar `confidence_score`,
THEN ele SHALL combinar pelo menos: entropia da distribuicao de brackets, largura do IC, spread/disagreement do ensemble NWP (se disponivel), estabilidade CP-a-CP, distance-to-threshold,
AND SHALL incluir `spike_risk` quando Fase 7 estiver ativa.

### REQ-CONF-3: Stay-out por baixa confianca
WHEN `confidence_score < threshold_pre_registrado`,
THEN o orquestrador SHALL marcar a decisao como `NO_TRADE` por padrao,
AND threshold SHALL ser otimizado contra a funcao-objetivo da REQ-DEC-3, nao escolhido manualmente.

---

## 5. Decisao de trade

### REQ-DEC-1: Computar YES e NO sempre
WHEN o sistema avaliar um mercado,
THEN ele SHALL computar `p_yes` e `p_no = 1 - p_yes` e comparar com `price_yes` e `price_no` do snapshot do mercado,
AND nao SHALL usar heuristica "NO-first" como unico filtro.

### REQ-DEC-2: Tres estados operacionais
WHEN o sistema decidir trade,
THEN ele SHALL classificar em exatamente um de: `NO_TRADE_RESOLVED`, `BLOCK_BUY_NO_LATE_SPIKE`, `OPPORTUNITY_ASSYMETRIC`,
AND SHALL bloquear `BUY_NO` quando `spike_risk >= threshold_spike` ou `distance_to_threshold <= margin_min`.

### REQ-DEC-3: Funcao-objetivo pre-registrada
WHEN o sistema otimizar thresholds,
THEN ele SHALL usar uma funcao-objetivo escolhida e congelada antes de ver resultados, dentre:
- `max(EV) sujeito a max_drawdown <= X`,
- `max(Sharpe) sujeito a coverage >= X`,
- `max(bracket_match_when_traded) sujeito a coverage >= X`,
AND SHALL gravar a escolha em `contracts/objective.md`.

> **Escopo (correcao 2026-05-30).** Tuning OFFLINE de thresholds usa a objetivo
> odds-free `max(bracket_match_when_traded) s.t. coverage` (a unica computavel sem odds
> historicas). As objetivos baseadas em `EV`/`Sharpe` so se aplicam AO VIVO, sobre forecasts
> vivos com odds do momento - nunca como otimizacao offline sobre odds passadas.

### REQ-DEC-4: Snapshot de odds ao vivo (somente no CP de forecast)
WHEN o sistema emitir um forecast ao vivo (Fase 8),
THEN ele SHALL, NAQUELE momento, capturar um snapshot dos contracts/brackets do mercado a partir de `eventUrl`, junto com `cp_utc` e SHA256,
AND esse snapshot serve APENAS para dar contexto de mercado ao forecast vivo (EV + dimensionamento Kelly), NAO e um dataset historico.

> **Escopo (correcao 2026-05-30).** Odds de Polymarket NUNCA foram um dataset historico.
> Nao ha (e nao havera) backtest de EV sobre odds passadas: odds so existem no instante do
> forecast vivo. A qualidade do MODELO e avaliada offline pela bateria de forecast-quality
> (bracket-match, RPS, ECE, SS-vs-persistencia + gates anti-nowcaster), que nao usa odds. O
> EV/Kelly e calculado AO VIVO combinando o `prob_dist` do modelo com o snapshot de odds do
> momento.

---

## 6. Modulo de late spike

### REQ-SPK-1: Label principal
WHEN o sistema treinar/avaliar `spike_risk`,
THEN ele SHALL usar como label principal `L1 = CrossThresholdAfterCP` (cruza para outro inteiro/bracket apos o CP operacional),
AND alternativas (`NewTmaxAfterCP`, `LateSpikeSize >= delta`) SHALL existir somente como ablations registradas.

### REQ-SPK-2: Causalidade no spike
WHEN o sistema computar features de spike,
THEN ele SHALL usar somente dados `<= cp_utc`,
AND nenhuma feature SHALL usar Tmax(D0) ou observacoes posteriores ao CP.

### REQ-SPK-3: Metricas obrigatorias do spike
WHEN o sistema reportar performance de `spike_risk`,
THEN ele SHALL incluir PR-AUC, recall@FPR<=0.05 e ECE do spike_risk em `reports/spike/<run_id>.md`.

---

## 7. Auditoria forense anti-nowcaster

### REQ-AUD-1: Protocolo executavel
WHEN o repositorio for atualizado,
THEN o sistema SHALL ter um runner reproduzivel `audits/run_h0_audit.py` cobrindo as 7 fases da secao 5.5 do v1
(lead-time, frozen observation, counterfactual same-temp, no-temperature model, horizon degradation, extreme spike, economic edge),
AND SHALL emitir `audits/<run_id>/h0_verdict.json` com:
`{ H0_rejected: bool, criterion: str, criterion_version: str, evidence_per_phase: [...] }`.
A ausencia desse arquivo SHALL marcar a execucao como FAIL.

### REQ-AUD-2: Gates anti-nowcaster pre-registrados
WHEN qualquer mudanca for promovida,
THEN ela SHALL passar nos seguintes gates (CI95% bootstrap onde aplicavel):
- `SS(1h) > 0.08` com IC95% excluindo 0,
- `SS(3h) > 0.10` com IC95% excluindo 0,
- `corr(y_hat, truth) - corr(y_hat, T_now) >= 0.20`,
- `|coverage_80 - 0.80| < 0.04`,
- `I_T_obs < 0.10` (importancia da observacao corrente nao dominante),
- `AUC contrafactual same-temp > 0.70`,
- ACF(residuos) sem lag significativo ate 7,
AND SHALL ganhar em >= 2/3 splits expanding-window.

> **Emenda v1.1 (criterion_version 1.1, 2026-05-29 - code review).** O gate
> `corr_diff` e REBAIXADO de gate (bloqueante) para **diagnostico reportado** (monitor):
> e calculado em anomalias (climatologia causal train-only por split, mesma base para
> `pred`/`truth`/`T_now`) e exibido no report, mas NAO entra em `aud2_passed`. Motivo:
> diferenca de correlacoes marginais e fragil/ruidosa em cidade unica com climo causal
> per-split, e pre-registrar threshold numa escala movel abre researcher-degrees-of-
> freedom. Sua intencao e coberta por `I_T_obs` + `SS(1h/3h)` + `AUC counterfactual` +
> curva de horizon-degradation (design 28.6). Gates sobreviventes e bateria completa:
> design 21.3.

### REQ-AUD-3: Reverse-import guard
WHEN qualquer arquivo em `core/` ou `nzwn/` importar de `audits/`,
THEN o pre-commit e o CI SHALL falhar a build,
AND `audits/` SHALL ser read-only em relacao a `core/` e `nzwn/`.

### REQ-AUD-4: Frozen observation test
WHEN o builder de dataset gerar features,
THEN cada feature SHALL ter metadata `last_input_ts` e `cp_utc`,
AND um teste automatizado SHALL rejeitar features com `last_input_ts > cp_utc`.

### REQ-AUD-5: Heteroscedasticidade
WHEN o sistema reportar IC,
THEN ele SHALL agrupar previsoes por quartis de largura do IC e reportar cobertura empirica por quartil,
AND nenhum quartil SHALL ter cobertura > `0.80 + 0.10` enquanto outro tem cobertura `< 0.80 - 0.10` (anti-ruido de calibracao).

### REQ-AUD-6: Thermo-anchor coasting
WHEN o sistema usar `Tmax(D-1)` ou `Tmin(D-1)` como features,
THEN o relatorio SHALL incluir `permutation_importance` desses recursos,
AND `permutation_importance(Tmax(D-1)) > 0.10` SHALL ser tratado como violacao de gate (modelo coasting).

---

## 8. Operacao e CLI

### REQ-OPS-1: CLI unica e exit codes honestos
WHEN o orquestrador for invocado via CLI,
THEN ele SHALL expor pelo menos os comandos: `forecast`, `postmortem`, `update-ar`, `audit`, `report`,
AND SHALL retornar exit codes nao-zero em qualquer falha (proibido soft-fail com `exit 0` e zero forecasts gerados),
AND SHALL aceitar `--dry-run` em `forecast` e `update-ar`.

### REQ-OPS-2: ASCII e `py -3`
WHEN o sistema gerar artefatos, logs JSON ou nomes de arquivos,
THEN o conteudo SHALL ser ASCII-only,
AND comandos documentados SHALL usar `py -3` como invocacao primaria (Windows-friendly), com `python3` como alias suportado.

### REQ-OPS-3: Logs estruturados JSON
WHEN o sistema executar `forecast` ou `postmortem`,
THEN cada evento SHALL ser um objeto JSON em uma linha (jsonl) com pelo menos:
`ts, level, run_id, cp_utc, cp_local, tz_name, component, event, duration_ms, data_quality, sha256_inputs[]`,
AND SHALL ser persistido em `artifacts/logs/<run_id>.jsonl`.

### REQ-OPS-4: Postmortem D+1
WHEN o dia local D0 fechar (apos `23:59` local + grace period),
THEN o `postmortem` SHALL ser executavel em modo automatico e emitir:
`reports/postmortem/<date_local>.md` com truth vs forecast por CP,
update do estado online (se Fase 6 ativa) com backup,
e atualizacao do verdict (se aplicavel).

### REQ-OPS-5: Backup e dedupe do estado online
WHEN o AR online atualizar estado,
THEN ele SHALL gravar backup em `artifacts/state/ar/<date>.bak.json` antes do update,
AND SHALL detectar e rejeitar updates duplicados pelo mesmo `(date_local, cp_utc)`.

---

## 9. Repositorio e qualidade

### REQ-REP-1: Estrutura de pastas
WHEN o repositorio for inicializado,
THEN ele SHALL ter (pelo menos) os diretorios:
`core/`, `nzwn/`, `audits/`, `experiments/`, `reports/`, `artifacts/`, `tests/`, `contracts/`, `references/legacy/`,
AND `references/legacy/` SHALL conter o v1 markdown original como fonte historica.

### REQ-REP-2: Golden tests
WHEN o sistema rodar `pytest`,
THEN existirao golden tests com inputs congelados (subset de `NZWN.csv`) e outputs esperados,
AND um diff em outputs SHALL falhar o test ate revisao manual e atualizacao explicita do golden.

### REQ-REP-3: CI baseline
WHEN um PR for aberto,
THEN o CI SHALL rodar: lint, type-check (se aplicavel), unit tests, golden tests, reverse-import guard (REQ-AUD-3), ASCII guard (REQ-OPS-2), determinism check (REQ-MOD-6).

### REQ-REP-4: Quarentena para scratch
WHEN qualquer codigo experimental ou backup for gerado,
THEN ele SHALL viver em `experiments/` ou `artifacts/scratch/`,
AND nao SHALL ser importado por `core/` ou `nzwn/`.

---

## 10. Metricas e gates de produto

### REQ-MET-1: Metrica primaria
WHEN o sistema avaliar promocao para producao,
THEN a metrica primaria SHALL ser a **qualidade de forecast no test split** - `bracket_match @ coverage` (REQ-MET-2) como metrica de topo, com RPS, ECE e SS-vs-persistencia como gates necessarios -, avaliada SEM odds,
AND `EV` e dimensionamento (Kelly) SHALL ser computados APENAS ao vivo no CP de forecast (REQ-DEC-4), a partir do `prob_dist` do modelo e do snapshot de odds do momento; NAO existe backtest de EV sobre odds historicas.

> **Correcao de escopo (2026-05-30).** Odds de Polymarket sao contexto de mercado ao vivo,
> nao um dataset. Logo a promocao do modelo se decide por forecast-quality offline; o EV
> realizado historico foi removido como metrica primaria (impossivel sem odds passadas). O EV
> esperado ao vivo + fracao de Kelly sao um produto do forecast vivo, auditados por execucao
> (REQ-MET-5), nao um criterio de treino offline.

### REQ-MET-2: Tabela coverage obrigatoria
WHEN qualquer relatorio (`reports/`, postmortem, auditoria) for emitido,
THEN ele SHALL conter a tabela `bracket_match @ coverage in {25%, 50%, 75%, 100%}`.

### REQ-MET-3: Splits temporais
WHEN o sistema avaliar qualquer modelo,
THEN ele SHALL usar expanding-window com >= 3 splits temporais,
AND SHALL reportar IC bootstrap (>= 1000 reamostragens) por metrica.

### REQ-MET-4: Kill criterion por fase
WHEN a Fase 3 (Ridge band-aware) nao bater baselines em >= 2/3 splits,
THEN o sistema SHALL parar e nao avancar para Fase 4 ate revisao de features/dados/labels.
A mesma regra de "ganho em >= 2/3 splits sem regredir gates" SHALL valer para Fases 4-8.

> **Emenda v1.1 - aceite da Fase 4 (criterion_version 1.1, 2026-05-29).** Na Fase 4, o
> "ganho" SHALL ser medido como **ablation pareado** que isola a contribuicao do NWP
> (modelo obs+NWP vs obs-only, e `LGBM(obs)` vs `LGBM(obs+NWP)`), com IC95% lo > 0 em
> `>= 2/3` splits - NAO como "NWP+residual bate max(persistence, climatology, ridge)".
> NWP e provedor de features forward + incerteza (design 29.5), preservando a estrutura
> residual REQ-MOD-3. Se o split-1 (2023) sair por ausencia de fonte causal (T-OPN-5a),
> a regra vira explicitamente `>= 2/2` e SHALL ser propagada as fases seguintes. Falha
> honesta -> Plano B (design 21.7): NWP rebaixado a feature/confianca, segue Fases 5/7/8;
> sem afrouxar threshold pos-resultado.

### REQ-MET-5: Live execution + sizing assumptions (congelado antes da Fase 8)
WHEN o sistema computar EV esperado e dimensionamento (Kelly) AO VIVO no CP de forecast (REQ-MET-1, REQ-DEC-4),
THEN ele SHALL usar uma **mecanica de execucao explicitamente congelada** em `contracts/execution.md` com no minimo:
- `fee_bps`: taxa de transacao em basis points por trade (default proposto v1: `200 bps` = 2% / lado, ajustar conforme Polymarket real),
- `slippage_model`: regra de preenchimento (default v1: `taker_at_quote` - paga `price_yes` em BUY YES e `price_no` em BUY NO; sem melhoria de preco),
- `entry_price_rule`: `mid` ou `ask` ou `last` - ESCOLHA UNICA por versao (default v1: `ask`),
- `position_sizing`: regra de dimensionamento. v1 default `1 unit notional` (sem Kelly); quando odds vivas estao disponiveis, `fractional_kelly` com `kelly_cap` documentado e permitido (REQ-DEC-3),
- `max_concurrent_positions`: limite de exposicao (default v1: `1 trade ativo por mercado por CP`),
- `time_in_force`: regra de expiracao (default v1: `cancel_unfilled_at_next_cp`),
AND mudancas em qualquer parametro SHALL bumpar `EXECUTION_VERSION`,
AND qualquer EV/sizing reportado **sem** `EXECUTION_VERSION` SHALL ser tratado como invalido (FAIL).

> **Correcao de escopo (2026-05-30).** Esta mecanica define como o EV esperado e a fracao de
> Kelly sao calculados NO INSTANTE do forecast vivo (modelo `prob_dist` + odds do momento). Como
> nao ha odds historicas, NAO existe "re-rodar todo o backtest shadow"; o que se congela e a
> formula de EV/sizing aplicada ao vivo, para que dois operadores cheguem ao mesmo numero dado o
> mesmo snapshot.

### REQ-MET-6: Tuning protocol (anti-overfit em thresholds)
WHEN o sistema otimizar thresholds (REQ-DEC-3, REQ-CONF-3),
THEN ele SHALL usar **nested walk-forward CV**:
- janela externa (test): nunca tocada durante tuning,
- janela intermediaria (validation): usada para ranquear configuracoes de threshold,
- janela interna (train): usada para fittar modelos auxiliares se necessario,
AND a configuracao final SHALL ser fixada **antes** de avaliar sobre o test split,
AND o sistema SHALL falhar se houver qualquer indicacao de "tuning sobre test" (ex.: rodar otimizacao mais de 1x apos olhar test).

---

## 11. Seguranca, compliance e licenca de dados

### REQ-SEC-1: Sem secrets em repo
WHEN o sistema usar credenciais (feeds METAR/TAF, mercados, NWP),
THEN credenciais SHALL viver em `.env` (git-ignored) ou em variaveis de ambiente,
AND SHALL ser referenciadas por nome nos logs (nunca valor).

### REQ-SEC-2: Dependencias pinadas
WHEN o sistema declarar dependencias,
THEN versoes SHALL ser pinadas (>= e <= explicitos ou `==` ou lockfile),
AND mudancas em `requirements.txt`/`pyproject.toml` SHALL passar por revisao.

### REQ-SEC-3: Atribuicao da fonte
WHEN o sistema documentar a origem de `NZWN.csv`,
THEN o `README.md` SHALL atribuir Iowa Environmental Mesonet (IEM ASOS) como fonte historica,
AND SHALL registrar termos de uso no `references/legacy/data_sources.md`.

---

## 12. Pendencias e decisoes em aberto (rastreadas)

| ID | Item | Default proposto | Bloqueia | Estado |
|----|------|------------------|----------|--------|
| OPN-1 | Validar contrato com resolver Polymarket (REQ-CON-2, completo) | Q default | **Fase 8** | aberto |
| OPN-1a | Validacao **minima** do resolver: estacao/ICAO, timezone, janela do dia (sem auditoria de Q) | NZWN, Pacific/Auckland, 00:00-23:59 local | **Fase 1** | proposto, congelar em T-0-3 |
| OPN-2 | Label principal de late spike | L1 = CrossThresholdAfterCP | (n/a) | proposto, congelado em REQ-SPK-1 |
| OPN-3 | Cutoffs operacionais "NO caro" | aprender via REQ-DEC-3 + REQ-MET-6 | **Fase 8** | aprender |
| OPN-4 | CP operacional padrao | 23 UTC = 11:00 NZ | (n/a) | proposto, congelado em REQ-CON-6 |
| OPN-5 | Fonte NWP a contratar | Open-Meteo (HFAPI + Single Runs); ECMWF IFS HRES + NCEP GFS v1 | **Fase 4** | **decidido em `contracts/nwp_source.md` v1.0** |
| OPN-5a | HFAPI vs Single Runs cross-check no overlap 2024-03..2025-12 | criterios em `contracts/nwp_source.md` secao "Cross-check obligation" | **Fase 4** | aberto |

**Regras de bloqueio (substituem qualquer fala anterior):**
- `OPN-1a` (validacao minima do resolver) SHALL estar fechado antes da **Fase 1**.
- `OPN-5` (fonte NWP) SHALL estar fechado antes da **Fase 4**.
- `OPN-1` (auditoria binaria de Q vs Polymarket, completa) SHALL estar fechado antes da **Fase 8**.
- `OPN-3` SHALL estar fechado antes da **Fase 8** via tuning protocol REQ-MET-6.

---

## Rastreabilidade

Cada requirement (`REQ-*`) deve ser referenciado por pelo menos uma task em `tasks.md` e por uma decisao de arquitetura em `design.md`. Requirements sem referencia em tasks sao considerados nao-implementados; tasks sem referencia em requirements sao considerados scope creep.
