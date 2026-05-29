# Design - Polymarket Tmax Forecaster (NZWN)

> **Spec version:** 1.0
> **Idioma:** PT-BR (ASCII em logs/CLIs/paths)
> **Companion:** ver `requirements.md`, `implementation-plan.md`, `tasks.md`
> **Escopo:** instanciacao concreta para NZWN (Wellington), arquitetura modular para replicacao futura.

Este documento descreve **como** o sistema sera construido. Cada decisao referencia o(s) requisito(s) que motiva(m).

---

## 1. Visao geral

O sistema e um pipeline intraday CP-aware que, para cada checkpoint `t` do dia local D0, emite uma distribuicao discreta sobre Tmax inteiro de NZWN, um IC80 e um `confidence_score` calibrado, e (Fase 7+) um `spike_risk`. Um orquestrador CLI executa `forecast`, `postmortem`, `update-ar`, `audit` e `report`. Auditoria forense roda como protocolo destrutivo separado, em modo read-only sobre `core/` e `nzwn/`.

```
                +---------------------+
                |  ingest (METAR/TAF, |
                |   NWP, market odds) |
                +----------+----------+
                           |
                           v
            +------------------------------+
            | snapshots (raw + SHA256)     |   REQ-DAT-1, REQ-DAT-4, REQ-DAT-5
            +------------------------------+
                           |
                           v
       +----------------------------------------+
       | dataset_builder (CP-aware, causal)     |   REQ-DAT-2, REQ-CON-5, REQ-AUD-4
       +----------------------------------------+
                  |               |
                  v               v
          +------------+   +-----------------+
          | baselines  |   | feature store   |
          | (persist./ |   | (per CP rows)   |
          | climo/NWP) |   +-----------------+
          +------------+          |
                  |               v
                  |    +----------------------------+
                  |    | core model                 |   REQ-MOD-1..MOD-6
                  |    | (Ridge -> NWP+residual)    |
                  |    +----------------------------+
                  |               |
                  v               v
          +-----------------------------+
          | calibration + confidence    |   REQ-MOD-4, REQ-CONF-1..3
          +-----------------------------+
                           |
                           v
          +-----------------------------+
          | spike_risk module           |   REQ-SPK-1..3
          +-----------------------------+
                           |
                           v
          +-----------------------------+
          | trading decision (YES/NO/   |   REQ-DEC-1..4
          | NO_TRADE/STAY_OUT)          |
          +-----------------------------+
                           |
                           v
       +-----------------------------------+
       | logs JSONL + reports + verdicts   |   REQ-OPS-3, REQ-AUD-1, REQ-MET-2
       +-----------------------------------+
```

---

## 2. Estrutura de pastas (REQ-REP-1)

```
polymarket-tmax-forecaster/
+-- core/                       # codigo agnostico de cidade (modelos, calibracao, decisao)
|   +-- ingest/                 # leitores METAR/TAF/NWP/odds, snapshots
|   +-- features/               # feature engineering causal CP-aware
|   +-- baselines/              # persistencia, climatologia, NWP cru
|   +-- models/                 # Ridge band-aware, residual learning, GBM
|   +-- calibration/            # conformal por CP/bucket
|   +-- confidence/             # confidence_score
|   +-- spike/                  # late spike module
|   +-- decision/               # YES/NO/NO_TRADE
|   +-- io/                     # snapshot writer, logs JSONL, hashing
|   +-- contracts/              # leitura/validacao dos contratos congelados
|   +-- cli/                    # orquestrador (forecast / postmortem / update-ar / audit / report)
+-- nzwn/                       # config, regimes, climatologia, calibradores especificos NZWN
|   +-- config/
|   |   +-- station.yaml        # ICAO, lat/lon, tz, CP operacional
|   |   +-- features.yaml       # quais features ativas
|   |   +-- model.yaml          # hyperparams por fase
|   +-- climatology/            # tabelas horarias smoothed
|   +-- regimes/                # GMM congelado (REQ-design - secao 7)
|   +-- calibrators/            # conformal por CP/bucket
+-- audits/                     # protocolo forense (READ-ONLY vs core/nzwn) - REQ-AUD-3
|   +-- phases/                 # 7 fases da secao 5.5 do v1
|   +-- run_h0_audit.py         # entry point
+-- experiments/                # ablations, NEGATIVE CONTROLS, scratch nao-promovido
+-- contracts/                  # versionados, congelados
|   +-- quantization.md         # REQ-CON-1
|   +-- resolver.md             # REQ-CON-2
|   +-- imputation.md           # REQ-DAT-3
|   +-- objective.md            # REQ-DEC-3
|   +-- features.md             # contrato de features e timestamps
+-- artifacts/                  # outputs de runs
|   +-- raw/{metar,taf,nwp,odds}/...
|   +-- snapshots/manifest.jsonl
|   +-- features/{date}/{cp}.parquet
|   +-- models/{model_id}/...
|   +-- state/ar/...
|   +-- logs/{run_id}.jsonl
|   +-- scratch/                # quarentena
+-- reports/                    # markdown human-readable
|   +-- postmortem/{date}.md
|   +-- audits/{run_id}/...
|   +-- shadow/...
+-- tests/                      # unit + integration + golden
|   +-- unit/
|   +-- integration/
|   +-- golden/                 # inputs congelados -> outputs esperados
+-- references/
|   +-- legacy/                 # v1 markdown original e outras referencias
|   +-- legacy/data_sources.md  # REQ-SEC-3
+-- pyproject.toml
+-- .kiro/specs/polymarket-tmax-forecaster/
```

**Hard rules:**
- `core/` e `nzwn/` **nao** importam de `audits/`, `experiments/`, `artifacts/scratch/` (REQ-AUD-3, REQ-REP-4).
- `contracts/` e versionado em git e tem hash (REQ-CON-1). Mudanca em contrato = nova `Q_VERSION` e re-execucao das auditorias.
- `references/legacy/` e read-only conceitualmente (somente fonte historica/atribuicao).

---

## 3. Stack tecnologico

| Camada | Escolha | Justificativa |
|--------|---------|---------------|
| Linguagem | Python 3.11 (CPython) | maturidade do ecossistema meteo/ML; `zoneinfo` nativo |
| CLI | `typer` | declarativo, gera ajuda; alinhado a REQ-OPS-1 |
| Dados tabulares | `polars` (preferido) ou `pandas` | causalidade explicita com `closed='left'`; performance em parquet |
| Storage local | `parquet` (features), `jsonl` (logs/manifest), `csv` (snapshots brutos) | reproduzivel, hashable |
| Modelagem (Fase 3-4) | `scikit-learn` Ridge; `lightgbm` para residual | seeds estaveis (REQ-MOD-6) |
| Calibracao | `mapie` ou implementacao propria conformal por CP | controle do bucketing |
| Time/zone | `zoneinfo.ZoneInfo("Pacific/Auckland")` | REQ-CON-4 |
| HTTP | `httpx` (sync, com retry) | timeouts e retries explicitos |
| Logging | `structlog` -> JSONL | REQ-OPS-3 |
| Tests | `pytest` + `pytest-randomly` desativado para testes deterministicos; `hypothesis` para edge cases | REQ-REP-2 |
| Lint/format | `ruff` + `ruff format`; `mypy` strict em `core/` | rapido, suficiente |
| CI | GitHub Actions (workflow `ci.yml`) | REQ-REP-3 |
| Pinagem | `pyproject.toml` + `uv.lock` (ou `pip-tools`) | REQ-SEC-2 |

GPU desligada por default; se ativada, registrar diferencas em `contracts/determinism.md` (REQ-MOD-6).

---

## 4. Contratos de dados

### 4.1 Schema do CSV historico (NZWN.csv, IEM ASOS)

Cabecalho real (auditado em `D:\Downloads\Wellington\NZWN.csv`):

```
station, valid, tmpf, dwpf, relh, drct, sknt, p01i, alti, mslp, vsby, gust,
skyc1..4, skyl1..4, wxcodes, ice_accretion_1hr, ice_accretion_3hr, ice_accretion_6hr,
peak_wind_gust, peak_wind_drct, peak_wind_time, feel, metar, snowdepth
```

Caracteristicas:
- 112.190 linhas, 2020-01-01 a 2026-05-27.
- `valid` esta em **UTC tz-naive** (precisa ser anotado como UTC ao parsear).
- Cadencia nominal 30 min, com SPECI ocasionais.
- Valor `M` representa missing (REQ-DAT-3).
- Temperatura **decimal** em Fahrenheit em `tmpf` e `dwpf`; **inteiro em °C** dentro do campo `metar` (ex.: `19/14`).

### 4.1.1 Truth types (tres sinais distintos, sem mistura)

Para evitar confusao entre o que e "verdade" do produto, o que alimenta features, e o que o modelo prediz, declaramos **tres** sinais com nomes distintos:

| Nome interno | O que representa | Origem | Onde pode ser usado |
|--------------|------------------|--------|---------------------|
| `T_obs_int` | inteiro em °C extraido do `metar` cru. **Verdade do produto** (resolucao do mercado). | regex sobre `metar` (ver 4.1, REQ-CON-3) | labels (`tmax_int`), avaliacao, decisao, auditoria. |
| `T_obs_dec` | decimal em °C derivado de `tmpf` (`(tmpf - 32) * 5/9`). | conversao da coluna `tmpf` | apenas features e diagnosticos (slopes, cross-check). **Proibido** alimentar como `truth` em qualquer lugar. |
| `T_latent_dec` | decimal em °C previsto pelo modelo (continuo, **antes** de quantizar). | saida bruta do modelo (Ridge, residual LGBM) | input para `Q(x)` -> `T_pred_int`; input para loss band-aware; input para suporte K. |

`T_pred_int = Q(T_latent_dec)` e o inteiro previsto. `prob_dist` opera sobre o suporte K de inteiros (ver 4.5.1).

**Hard rule:** nenhum codigo em `core/` ou `nzwn/` pode atribuir `T_obs_dec` ou `T_latent_dec` a uma variavel chamada `truth*`. Apenas `T_obs_int` (e os labels `tmax_int`, `tmin_int` derivados dele) sao "verdade".

### 4.1.2 Politica de parse do METAR (REQ-CON-3 + REQ-CON-8)

Pseudocodigo do extrator:

```
def parse_tmp_c_int(metar_raw: str, tmpf: float | None) -> tuple[int | None, str]:
    """Returns (tmp_c_int, data_quality_flag)."""
    if metar_raw is None or metar_raw.strip() == "":
        # fallback permitido (REQ-CON-8)
        if tmpf is not None and not math.isnan(tmpf):
            return (round((tmpf - 32) * 5 / 9), "imputed")
        return (None, "missing")

    # 1) regex padrao - grupo TT/DD em °C inteiro
    m = re.search(r"\s(M?\d{1,2})/(M?\d{1,2})\s", metar_raw)
    if m:
        tt = m.group(1)
        sign = -1 if tt.startswith("M") else 1
        digits = tt.lstrip("M")
        value = sign * int(digits)
        # plausibilidade NZWN: -10 <= T <= 40 °C
        if -10 <= value <= 40:
            return (value, "ok")
        # 2) valor implausivel -> nao aplicar fallback (REQ-CON-8); marcar missing
        return (None, "missing")

    # 3) regex falhou em metar legivel -> NAO aplicar fallback (REQ-CON-8)
    return (None, "missing")
```

Casos cobertos:
- `19/14` -> `(19, "ok")`,
- `M02/M05` -> `(-2, "ok")`,
- `metar=""` com `tmpf=64.4` -> `(18, "imputed")`,
- `metar` legivel mas sem grupo `TT/DD` -> `(None, "missing")` (NAO usa tmpf como fallback),
- `metar` com grupo improvavel `99/99` -> `(None, "missing")`.

Multiplos grupos: o regex captura o **primeiro** match valido. Auditoria deve flagrar mensagens com >1 match e divergencia entre eles em `reports/eda/decimal_vs_int_check.md`.

### 4.2 Mapping CSV -> dominio interno

| Coluna CSV | Tipo interno | Unidade interna | Observacao |
|------------|--------------|-----------------|------------|
| `valid` | `datetime[UTC]` | UTC | converter tz-naive -> tz-aware UTC; derivar `cp_local` via `Pacific/Auckland` |
| `tmpf` | `float` | °C (`(tmpf-32)*5/9`) | uso decimal interno; nunca para gerar `k_obs` (REQ-CON-3) |
| `dwpf` | `float` | °C | idem |
| `relh` | `float` | % | |
| `drct` | `float` | graus (0-360) | sin/cos features |
| `sknt` | `float` | knots | |
| `p01i` | `float` | inches | converter para mm; flag `precip_recent` |
| `alti` | `float` | inHg | converter para hPa para QNH; tendencia 3h, 6h |
| `mslp` | `float?` | hPa | frequentemente `M` no NZWN; usar `alti` como fallback |
| `vsby` | `float` | miles | converter para km |
| `gust` | `float?` | knots | flag `gust_present` |
| `skyc1..4` | str | enum (NCD, FEW, SCT, BKN, OVC, ...) | features de cobertura |
| `skyl1..4` | float | feet | converter para metros; ceiling minimo |
| `wxcodes` | str | tokens | flags: `has_rain, has_thunder, has_haze` etc. |
| `metar` | str | bruto | fonte de **verdade** para `T_obs_int` (REQ-CON-3, REQ-CON-8). Regex padrao: `r"\s(M?\d{1,2})/(M?\d{1,2})\s"`; prefixo `M` -> sinal negativo. Para METAR sem grupo TT/DD, ou com grupos multiplos, ver politica em 4.1.2. |

### 4.3 Tabela canonica `metar_observations`

```
station: str (NZWN)
ts_utc: datetime[UTC]
ts_local: datetime[Pacific/Auckland]
date_local: date
tmp_c_dec: float                # de tmpf
tmp_c_int: int                  # extraido de metar
dwp_c_int: int
wind_dir_deg: float?
wind_speed_kt: float?
wind_gust_kt: float?
qnh_hpa: float?
pressure_3h_delta_hpa: float?   # rolling closed='left'
vis_km: float?
ceiling_m: float?
sky_cover: enum?                # max(skyc1..4)
wx_flags: bitset
precip_mm_30m: float?
data_quality: dict[str, enum]   # ok|imputed|missing por feature
source_metar_raw: str
snapshot_sha256: str
```

### 4.4 Labels (`tmax_labels`)

```
date_local: date
tmax_int: int                   # max diario de tmp_c_int em 24h locais (REQ-CON-4)
tmax_ts_utc: datetime[UTC]
tmax_ts_local: datetime[Pacific/Auckland]
tmin_int: int
n_obs_in_day: int
day_complete: bool              # REQ-CON-7: n_obs>=40, max_gap<=120min, 1 obs/quartil
late_spike_l1__cp_<HH>: bool    # uma coluna por CP em CP_SET (REQ-CON-6)
                                # late_spike_l1 = (k_eod != k_cp)
                                # k_cp  = max(tmp_c_int para ts_local em [00:00, cp_local))
                                # k_eod = max(tmp_c_int para ts_local em [00:00, 24:00))
```

> **Definicao operacional do late spike L1 (REQ-SPK-1):**
> Trabalhamos exclusivamente sobre `T_obs_int` (4.1.1). Para cada CP do `CP_SET`:
> ```
> k_cp(date_local, cp)  = max{tmp_c_int(ts) | ts_local in [00:00, cp_local(cp))}
> k_eod(date_local)     = max{tmp_c_int(ts) | ts_local in [00:00, 24:00)}
> late_spike_l1(date_local, cp) = (k_eod(date_local) != k_cp(date_local, cp))
> ```
> Sem `t_so_far_max_c_dec`, sem ambiguidade sobre Q. Auditavel diretamente sobre o dataset.

### 4.5 Feature row por CP (`features_per_cp`)

Uma linha por `(date_local, cp_utc)`. Particionado por `date_local`.

```
date_local, cp_utc, cp_local, tz_name
station, dataset_version, snapshot_sha256

# direct observed (until cp)
t_so_far_max_c_int: int                   # max de tmp_c_int em [00:00 local, cp]
t_so_far_max_ts_utc: datetime[UTC]
t_so_far_max_age_min: int
last_obs_tmp_c_int: int
last_obs_dwp_c_int: int

# trend & dynamics (rolling, closed='left')
slope_3h_c_per_h: float
slope_6h_c_per_h: float
time_since_new_max_min: int                # platô / travao
plateau_score: float

# wind / regime
wind_dir_deg, wind_speed_kt, wind_gust_kt
wind_change_3h_deg, wind_speed_max_3h_kt
wx_flags_recent: bitset                    # rain, fog, thunder
ceiling_min_3h_m, vis_min_3h_km

# pressure
qnh_hpa, dp_3h, dp_6h

# climatology baseline
clim_tmax_c_dec: float                     # smoothed climatology tabela mensal
clim_tmax_int: int
clim_residual_so_far_c: float

# NWP (Fase 4+)
nwp_runs: List[{model, run_time_utc, lead_h, valid_time_utc, t2m_c_dec, sha256}]
nwp_mean_c_dec: float?
nwp_spread_c: float?
nwp_disagreement_score: float?
nwp_selected_run_id: str?                   # 4.5.2
nwp_selected_lead_h: int?

# regime (NZWN, secao 7)
regime_id: int                              # 0..7 GMM congelado
regime_proba: List[float]

# previous days (REQ-AUD-6)
tmax_d_minus_1_int: int
tmin_d_minus_1_int: int

# flags
data_quality: dict[str, enum]
feature_max_ts_utc: datetime[UTC]           # maior ts entre features (deve ser <= cp_utc)
```

### 4.5.1 Suporte K (conjunto de inteiros candidatos para `prob_dist`)

Para evitar que cada implementacao defina o suporte da `prob_dist` de forma diferente, o suporte K e calculado por uma regra unica:

```
def support_K(date_local, cp_utc, climo, nwp) -> list[int]:
    p10 = min(climo.tmax_p10, nwp.tmax_p10) if nwp else climo.tmax_p10
    p90 = max(climo.tmax_p90, nwp.tmax_p90) if nwp else climo.tmax_p90
    k_min = floor(p10 + 0.5) - 2
    k_max = floor(p90 + 0.5) + 2
    # bounds plausiveis NZWN
    k_min = max(k_min, -10)
    k_max = min(k_max, 40)
    return list(range(k_min, k_max + 1))
```

Regras:
- `prob_dist` SHALL somar exatamente `1.0` sobre `support_K`.
- Mass alocada **fora** de `support_K` SHALL ser `0` (nao "leakage de probabilidade" para inteiros distantes).
- O suporte K e parte do snapshot do forecast (REQ-MOD-1) e gravado em `forecasts.support_k`.
- Mudancas na regra acima exigem bump em `Q_VERSION`.

### 4.5.2 NWP selection rule v1 (qual run/lead entra no CP)

Para um `(date_local, cp_utc)` e uma fonte NWP `M`, a regra de selecao v1 e deterministica:

```
def select_nwp_v1(cp_utc, date_local, model_M) -> NwpSnapshot | None:
    # 1) latest run disponivel cujo run_time_utc <= cp_utc - safety_margin
    safety_margin = timedelta(minutes=30)   # latencia tipica de publicacao
    candidate_runs = [r for r in available_runs(model_M)
                      if r.run_time_utc <= cp_utc - safety_margin]
    if not candidate_runs:
        return None
    selected_run = max(candidate_runs, key=lambda r: r.run_time_utc)

    # 2) anchor de valid_time = hora local do Tmax climatologico (NZWN ~14-15 local)
    target_valid_utc = climo.tmax_hour_local(date_local).to_utc()
    # 3) lead = (target_valid - selected_run.run_time_utc) em horas,
    #    arredondado para multiplo do passo do modelo (ex.: 3h GFS, 1h ECMWF HRES)
    lead_h_raw = (target_valid_utc - selected_run.run_time_utc).total_seconds() / 3600
    lead_h = round_to_step(lead_h_raw, step=model_M.lead_step_h)

    # 4) lead deve estar disponivel; senao escolher o lead disponivel mais proximo
    if lead_h not in selected_run.available_leads:
        lead_h = min(selected_run.available_leads, key=lambda l: abs(l - lead_h_raw))
    return selected_run.snapshot_for_lead(lead_h)
```

**Hard rules:**
- `safety_margin` SHALL ser configuravel em `nzwn/config/model.yaml` mas registrada por versao.
- A escolha SHALL ser deterministica: mesmo `(cp_utc, date_local, model_M)` -> mesmo `selected_run` e `lead_h`.
- `nwp_selected_run_id` e `nwp_selected_lead_h` SHALL ser registrados em `forecasts` e em `features_per_cp`.
- Mudancas em `safety_margin` ou `target_valid_anchor` SHALL bumpar a versao do modelo (`MODEL_VERSION`).

Para ensemble (multiplos modelos): aplicar a regra acima por modelo independentemente; agregar via media ponderada e spread (REQ-MOD-3).

### 4.6 Forecast row (`forecasts`)

```
forecast_id: uuid
run_id: uuid
date_local, cp_utc, cp_local, tz_name
station: NZWN
model_version, dataset_version, snapshot_sha256
prob_dist: dict[int -> float]                # P(Tmax = k) sobre support_k
support_k: list[int]                          # 4.5.1
p50_int: int
ic80_low_int: int
ic80_high_int: int
confidence_score: float (0..1)
spike_risk: float? (0..1)                    # Fase 7+
data_quality_summary: enum (ok|degraded|fail)
notes: str?
```

### 4.7 Decision row (`decisions`)

```
forecast_id (FK)
market_id: str                                # eventUrl
contracts_snapshot_sha256
contracts: list[{name, range, price_yes, price_no, ts_utc}]
decision: enum (NO_TRADE_RESOLVED, BLOCK_BUY_NO_LATE_SPIKE, OPPORTUNITY_ASSYMETRIC, BUY_YES, BUY_NO, ...)
expected_value: float
threshold_set_id: str                          # quais thresholds estavam ativos
objective_version: str                         # REQ-DEC-3
```

### 4.8 Verdict file (`audits/<run_id>/h0_verdict.json`) — REQ-AUD-1

```json
{
  "run_id": "...",
  "criterion": "anti-nowcaster-v1",
  "criterion_version": "1.0",
  "H0_rejected": true,
  "evidence_per_phase": [
    {"phase": "lead_time", "passed": true, "details": {...}},
    {"phase": "frozen_obs", "passed": true, "details": {...}},
    {"phase": "counterfactual_same_temp", "passed": true, "details": {"auc": 0.78}},
    {"phase": "no_temperature_model", "passed": true, "details": {"residual_skill": 0.13}},
    {"phase": "horizon_degradation", "passed": true, "details": {...}},
    {"phase": "extreme_spike", "passed": false, "details": {...}},
    {"phase": "economic_edge", "passed": null, "details": {"reason": "phase_not_active"}}
  ],
  "gate_violations": [],
  "created_utc": "..."
}
```

---

## 5. Tempo, timezone e janelas

- **UTC** e a unica representacao interna em colunas `*_utc`.
- Conversao para local usa `Pacific/Auckland` (`zoneinfo`). Reportar sempre `tz_name` (REQ-OPS-3).
- "Dia local D0": `[00:00, 23:59:59.999]` em hora local; mapeado para UTC dinamicamente (DST varia ~13:00 -> ~11:00 UTC inicio do dia).
- Tmax(D0) e calculado sobre **24h completas** do dia local (REQ-CON-4).
- DST testado com casos: 1 dia antes, dia da transicao, 1 dia depois, em ambas as direcoes (`tests/unit/test_dst.py`).

**Decisao tecnica:** funcao auxiliar central `core/io/timeutil.py::day_local_window(date_local) -> (utc_start, utc_end)`. Uso obrigatorio em qualquer agregacao diaria.

---

## 6. Fluxo CP-aware (sequencia tipica)

Para `cp_utc = 23:00 UTC` (CP operacional NZWN, REQ-CON-4 + decisao 21.1):

1. **Snapshot** (REQ-DAT-1): persistir METAR cru ate `cp_utc - epsilon` em `artifacts/raw/metar/`. SHA256 do dia em `manifest.jsonl`.
2. **dataset_builder.build(date_local, cp_utc)** (REQ-DAT-2):
   - Le snapshots, monta `metar_observations` filtrado a `ts_utc < cp_utc` (closed='left').
   - Calcula features (rolling com `closed='left'`).
   - Verifica `feature_max_ts_utc <= cp_utc`. Se falhar, **erro** (REQ-CON-5).
   - Emite `features_per_cp.parquet`.
3. **Baselines** (Fase 2):
   - `persistence(t-1h, t-3h)`,
   - `climatology_smoothed(date, hour_local)`,
   - `nwp_raw(latest_available_run_le_cp)`.
4. **Core model** (Fase 3+):
   - Ridge band-aware sobre `delta_vs_climo`,
   - depois `NWP_baseline + residual` (Fase 4),
   - emite `prob_dist` e `p50_int`.
5. **Calibracao** (Fase 5): conformal por CP -> ajusta `prob_dist`, deriva `IC80`.
6. **Confidence** (Fase 5/6): combina sinais (REQ-CONF-2) -> `confidence_score`.
7. **Spike risk** (Fase 7): emite `spike_risk` calibrado.
8. **Decision** (Fase 8): `decision_engine` consulta odds snapshot, computa EV, classifica em um dos 3 estados (REQ-DEC-2).
9. **Persistencia**: gravar `forecasts` e `decisions`, com SHA256 dos artefatos de modelo.
10. **Logs**: JSONL para `artifacts/logs/<run_id>.jsonl` (REQ-OPS-3).

---

## 7. Regimes (NZWN especifico)

**Decisao (REQ - secao 21.10 do v1):** clustering fixo via **GMM com 6-8 componentes**, treinado **uma vez** sobre features simples ao amanhecer local (`06:00-08:00` local em sliding window):
- vento_dir (`sin`, `cos`),
- vento_int (kt),
- QNH (hPa),
- tendencia QNH 6h.

Artefato: `nzwn/regimes/gmm_v1.pkl` + `regimes/manifest.json` (`features`, `means`, `covariances`, `n_components`, `seed`, `train_window`).

**Proibicoes:** criar regimes ad-hoc por sprint, mudar nomes, retreinar sem revalidar via auditoria forense.

**Uso:**
- feature `regime_id` e `regime_proba` no core,
- segmentacao de metricas por regime,
- gatilho de baixa confianca quando `regime_id` e raro no historico (`<1%`).

---

## 8. Modelagem por fase

| Fase | Modelo | Saida principal | Comparacao |
|------|--------|-----------------|------------|
| 2 | persistencia + climatologia smoothed; `prob_dist` empirico condicional | `prob_dist`, `p50_int` | baseline obrigatorio |
| 3 | Ridge sobre `delta_vs_climo` (band-aware loss); `prob_dist` via softmax band-aware com `tau` congelado | `T_latent_dec`, `prob_dist` | vs persistencia + climatologia |
| 4 | NWP residual learning (LightGBM) + features de spread/disagreement | `T_latent_dec`, `prob_dist` | vs NWP cru, vs Ridge |
| 5 | Calibracao conformal por CP | `prob_dist` calibrado, IC80 | risk-coverage, ECE |
| 6 | (opcional) AR(7) residual online | `T_latent_dec` corrigido | DM-test vs persistencia |
| 7 | Modulo `spike_risk` (LightGBM) | `spike_risk` calibrado | PR-AUC, recall@FPR |
| 8 | Decision engine + threshold tuning (nested walk-forward) | `decision`, EV | EV realizado vs esperado |

**NEGATIVE CONTROLS** (em `experiments/`, nunca em `core/`):
- nowcast blend com observacao corrente (REQ-AUD-2 mede skill que e devida apenas a `T_now`),
- bias correction estatica `.pkl` sem revalidacao,
- blend convexo `beta * NWP + (1-beta) * ML`,
- `prob_dist` gaussiano com `sigma=MAE` (proibido em `core/` por gerar falso conforto - OK apenas como ablation rotulada).

**Contrato de baselines (Fase 2):**

- **Climatologia smoothed:** treinada **apenas no train split** (janela >= 12 meses, REQ - secao 16 v1). Nunca usar dados do test split nem do validation split. O artefato gerado e versionado por split em `nzwn/climatology/<train_window_id>/`.
- **`prob_dist` empirico condicional (substitui qualquer "gaussiana ingenua"):**
  ```
  P(k_eod = k | month, cp, k_cp) = freq empirica no train split,
                                    suavizada via Laplace (alpha=1) e
                                    truncada ao support_K (4.5.1).
  ```
  Quando o conditioning bucket tem `n < 30` no train split, fazer fallback para o bucket marginal `(month, cp)` e logar `data_quality.prob_dist = "fallback_marginal"`.
- **Persistencia:** `p50_int = k_cp`; IC ingenuo igual a `[k_cp - 1, k_cp + 1]` apenas como sanity, nao como producao.

> **Justificativa:** distribuicao empirica condicional e auditavel (basta inspecionar a tabela), nao introduz hiperparametros tunaveis e nao gera falso conforto de calibracao.

### 8.1 Loss band-aware (REQ-MOD-2)

```python
def band_aware_loss(y_pred: float, y_true_int: int, alpha: float = 1.0, mode: str = "linear") -> float:
    low, high = y_true_int - 0.5, y_true_int + 0.5
    if low <= y_pred < high:
        return 0.0
    dist = max(low - y_pred, y_pred - high)
    return alpha * dist if mode == "linear" else alpha * dist * dist
```

### 8.1.1 De `T_latent_dec` para `prob_dist` (Fase 3+)

Para transformar a saida continua do modelo (`T_latent_dec`) em `prob_dist` discreta sobre `support_K`, usamos **softmax band-aware** com temperatura `tau` congelada:

```python
def latent_to_prob_dist(t_latent_dec: float, support_k: list[int], tau: float, mode: str = "linear") -> dict[int, float]:
    losses = {k: band_aware_loss(t_latent_dec, k, alpha=1.0, mode=mode) for k in support_k}
    logits = {k: -losses[k] / tau for k in support_k}
    z = max(logits.values())
    exp_logits = {k: math.exp(v - z) for k, v in logits.items()}  # estabilidade numerica
    s = sum(exp_logits.values())
    return {k: v / s for k, v in exp_logits.items()}
```

Hard rules:
- `tau` SHALL ser fixado em `nzwn/config/model.yaml` (default v1: `tau = 0.5` para `mode=linear`).
- `tau` SHALL ser revisado **apenas** entre versoes do modelo, **nunca** durante tuning de threshold (anti-overfit).
- Mudar `tau` exige bumpar `MODEL_VERSION` e re-rodar a auditoria forense.
- Alternativa explicitamente proibida em `core/`: `prob_dist` parametrico Gaussiano `N(T_latent_dec, sigma)` (mantido apenas em `experiments/` como ablation rotulada).

### 8.2 Calibracao conformal (REQ-MOD-4)

- por CP (todos os `cp_utc` ativos: ex. `21Z`, `22Z`, `23Z`),
- opcional por bucket `(month, regime, cp)` com `n_min=200`,
- janela curta auditada (60-90 dias) + sazonal de 12 meses como cross-check (REQ - secao 16),
- emitir `IC80_low_int`, `IC80_high_int` aplicando `Q` no IC continuo.

### 8.3 Confidence score (REQ-CONF-1, REQ-CONF-2)

`confidence_score = sigmoid(w . phi)` onde `phi` agrega:
- `-entropy(prob_dist)` normalizado,
- `-(IC80_high - IC80_low)` normalizado,
- `-nwp_spread` normalizado (se disponivel),
- `-Var(p50_cp_anteriores)` (estabilidade CP-a-CP),
- `+min(|p50_dec - (k+0.5)|, |p50_dec - (k-0.5)|)` (distance-to-threshold),
- `-spike_risk` (Fase 7+).

Pesos `w` aprendidos por logistic regression contra `bracket_correct`, calibrados por isotonic regression. ECE auditado em `audits/confidence_audit.json` (REQ-CONF-1).

---

## 9. Modulo de late spike

**Label L1** (REQ-SPK-1, definicao operacional em 4.4): para cada `(date_local, cp)` com `cp in CP_SET`,
```
k_cp(date_local, cp)  = max(tmp_c_int para ts_local em [00:00, cp_local(cp)))
k_eod(date_local)     = max(tmp_c_int para ts_local em [00:00, 24:00))
late_spike_l1(date_local, cp) = (k_eod != k_cp)
```
**Apenas inteiros (`T_obs_int`)** sao usados. Nao ha ambiguidade de Q nem dependencia de `T_obs_dec`.

**Features causais** (REQ-SPK-2):
- `time_since_new_max_min`, `slope_3h`, `slope_6h`,
- vento (mudanca de regime), QNH delta,
- `vis_km`, `ceiling_m`, `wx_flags_recent` (especialmente `clearing` proxy),
- pos-chuva: `precip_mm_3h_so_far`, `dwp_dec - tmp_dec` (proxy de umidade),
- `nwp_disagreement_score`, `regime_id` (raro = mais risco).

**Modelo:** LightGBM binario, train com early stopping e seeds fixas (REQ-MOD-6). Calibrado por isotonic regression.

**Saidas:**
- `spike_risk` (probabilidade calibrada),
- flag `block_buy_no` quando `spike_risk >= threshold_spike`.

---

## 10. Decision engine

```
def decide(forecast: ForecastRow, market: MarketSnapshot, thresholds: Thresholds) -> Decision:
    p_yes = compute_p_yes(forecast, market.contracts)
    p_no  = 1 - p_yes
    edge_yes = p_yes - market.price_yes
    edge_no  = p_no  - market.price_no

    if forecast.confidence_score < thresholds.min_confidence:
        return NO_TRADE("low_confidence")
    if forecast.spike_risk >= thresholds.spike_block:
        return BLOCK_BUY_NO_LATE_SPIKE
    if market.price_no >= thresholds.no_too_expensive:
        return NO_TRADE_RESOLVED
    if edge_yes >= thresholds.min_edge_yes:
        return OPPORTUNITY_ASSYMETRIC(side="YES", size=...)
    if edge_no >= thresholds.min_edge_no and forecast.spike_risk < thresholds.spike_block:
        return BUY_NO(...)
    return NO_TRADE("no_edge")
```

Thresholds aprendidos via REQ-DEC-3 + REQ-MET-6 (nested walk-forward) - **nunca** otimizados sobre o test split. Versao do conjunto registrada em `decisions.threshold_set_id`.

### 10.1 Shadow execution model (REQ-MET-5)

Mecanica de execucao congelada em `contracts/execution.md` (`EXECUTION_VERSION=1.0`):

| Parametro | Default v1 | Notas |
|-----------|-----------|-------|
| `fee_bps` | 200 (= 2%/lado) | ajustar quando Polymarket fee real for confirmado |
| `slippage_model` | `taker_at_quote` | sem improvement; paga `price_yes` em BUY YES e `price_no` em BUY NO |
| `entry_price_rule` | `ask` | unico valor por versao - sem mistura mid/ask/last |
| `fill_rule` | `assume_full_fill` | ablation: `partial_fill_with_min_size` em `experiments/` |
| `position_sizing` | `1 unit notional` | sem Kelly nem martingale na v1 |
| `max_concurrent_positions` | `1 trade ativo por mercado por CP` | |
| `time_in_force` | `cancel_unfilled_at_next_cp` | |

Pseudo-codigo do simulador:

```python
def shadow_simulate(decision: Decision, market: MarketSnapshot, exec: ExecutionContract, truth: TmaxLabel) -> TradeResult:
    if decision.side == "NO_TRADE":
        return TradeResult(pnl=0.0, filled=False, ...)
    side = decision.side                       # BUY_YES | BUY_NO
    entry_price = market.contracts[decision.contract_id].price_for_side(side, exec.entry_price_rule)
    notional = exec.position_sizing
    fee = entry_price * notional * exec.fee_bps / 1e4
    if not _filled(decision, market, exec):
        return TradeResult(pnl=0.0, filled=False, ...)
    payoff = 1.0 if _market_resolved_in_favor(side, decision.contract_id, truth) else 0.0
    pnl = (payoff - entry_price) * notional - 2 * fee   # entrada + saida assumida implicita
    return TradeResult(pnl=pnl, filled=True, fee_paid=2*fee, entry_price=entry_price, ...)
```

Saidas obrigatorias do backtest shadow:
- `equity_curve.parquet` (por timestamp),
- `trades.parquet` (uma linha por trade),
- `reports/shadow/<run_id>.md` com EV realizado vs esperado, drawdown, Sharpe, calibracao por bucket de EV.

EV reportado **sem** referencia a `EXECUTION_VERSION` SHALL ser tratado como invalido.

### 10.2 Tuning protocol (REQ-MET-6) - nested walk-forward

```
splits temporais (expanding-window, >= 3 splits):
+--------+-------------+-------------+
|  TRAIN |   VALIDATION |    TEST    |
+--------+-------------+-------------+
            ^                  ^
            |                  |
    threshold tuning         metric reporting
```

Regras:
- TRAIN: fitar modelos auxiliares (climatologia, residual LGBM, GMM regimes etc.).
- VALIDATION: rodar a otimizacao de thresholds via funcao-objetivo (`contracts/objective.md`). Pode-se rodar grid search ou bayesian opt aqui.
- TEST: avaliacao final, **uma unica vez** por versao do `threshold_set_id`. Multiplas avaliacoes no test split SHALL ser tratadas como overfit (REQ-MET-6).
- Nenhum hiperparametro do core (incluindo `tau` da Fase 3, `safety_margin` NWP, `min_confidence`) pode ser ajustado em VALIDATION e re-avaliado no TEST. So thresholds operacionais (`min_edge_yes`, `min_edge_no`, `no_too_expensive`, `min_confidence`, `spike_block`).

Saida obrigatoria do tuning:
- `artifacts/tuning/<threshold_set_id>/results.parquet` com 1 linha por configuracao avaliada,
- `artifacts/tuning/<threshold_set_id>/winner.json` com a configuracao escolhida + metricas em VALIDATION,
- relatorio `reports/tuning/<threshold_set_id>.md` documentando o protocolo executado.

---

## 11. Auditoria forense (`audits/`)

`audits/run_h0_audit.py` orquestra as 7 fases. Cada fase produz um relatorio markdown em `reports/audits/<run_id>/` e um bloco em `h0_verdict.json` (REQ-AUD-1).

| Fase | Implementacao resumida | Gate |
|------|------------------------|------|
| 1. Lead-time forecast audit | curva de skill e PR-AUC para spikes vs lead | skill positiva > 3h antes |
| 2. Frozen observation test | varre `feature_max_ts <= cp_utc` para todas features (REQ-AUD-4) | sem violacao |
| 3. Counterfactual same-temp | pares com mesma `t_so_far_max_c_int`, regimes diferentes | AUC > 0.70 (REQ-AUD-2) |
| 4. No-temperature model | retreina sem ancoras termicas; verifica skill residual | skill > 0 com IC95% |
| 5. Horizon degradation | curva por CP; nao explodir apenas no fim do dia | monotonia razoavel |
| 6. Extreme spike audit | top 1%/5% Delta T; calibracao condicional | tail score nao-degenerado |
| 7. Economic edge | EV esperado vs realizado em shadow | dentro dos ICs |

`audits/` tem hook de pre-commit que checa imports (REQ-AUD-3): `from core import ...` em `audits/` e OK; `from audits import ...` em `core/` ou `nzwn/` e proibido.

---

## 12. CLI e logs

CLI raiz (`tmax`):

```
tmax forecast    --station NZWN --cp 23 --date 2026-05-28 [--dry-run]
tmax postmortem  --station NZWN --date 2026-05-27
tmax update-ar   --station NZWN --date 2026-05-27
tmax audit       --run-id <id> [--phase 1|2|3|4|5|6|7|all]
tmax report      --kind {coverage,calibration,spike,shadow} --window 30d
```

- Cada comando retorna exit-code != 0 em qualquer falha (REQ-OPS-1).
- Log JSONL gravado por padrao em `artifacts/logs/<run_id>.jsonl` (REQ-OPS-3).
- `--config` aceita override pontual; defaults vem de `nzwn/config/*.yaml`.
- ASCII-only nos outputs (REQ-OPS-2).

---

## 13. Determinismo e reprodutibilidade

- Seeds: `random=42`, `numpy=42`, `lightgbm.seed=42`, `lightgbm.bagging_seed=42`, `lightgbm.feature_fraction_seed=42` (REQ-MOD-6). Documentadas em `nzwn/config/model.yaml`.
- CI step `determinism`: roda `tmax train --seed 42` duas vezes; compara SHA256 dos artefatos. Toleria zero diff em CPU.
- Threading: `OMP_NUM_THREADS=1` em CI para evitar nondeterminismo de paralelismo. Ajustar fora de CI.
- GPU: desligada por default. Habilitar so via flag explicita; documentar diferenca esperada.

---

## 14. Observabilidade

- **Logs**: JSONL com `event` enumerado (`ingest.start`, `ingest.snapshot.write`, `dataset.build`, `model.predict`, `calibration.apply`, `decision.emit`, `audit.phase.*`).
- **Metrics local**: relatorios markdown em `reports/`. Sem Prometheus/Grafana no v1.
- **Hashing**: `sha256_hex(file)` chamado para inputs criticos: snapshots METAR/TAF/NWP, modelo treinado, dataset_version. Registrado em `forecasts.snapshot_sha256` e nos eventos de log.
- **Run id**: UUID v4 por execucao do CLI; passado como `run_id` em todos os eventos.

---

## 15. Decisoes ja congeladas (origem v1)

| Decisao | Valor | Motivo |
|---------|-------|--------|
| Q(x) default | `floor(x + 0.5)` | round-half-up; simples e auditavel (REQ-CON-1) |
| B(k) default | `[k - 0.5, k + 0.5)` | conjugado de Q; cobre eixo real sem ambiguidade |
| CP set oficial | `[20:00, 21:00, 22:00, 23:00] UTC` | REQ-CON-6; CP operacional = `23:00` |
| `day_complete` | `n_obs>=40 & max_gap<=120m & 1 obs/quartil` | REQ-CON-7 |
| Fallback policy | `imputed` so se metar ausente; max 0.5% | REQ-CON-8 |
| Verdade observacional (`T_obs_int`) | inteiro do `metar` cru | mercado resolve sobre METAR publicado (REQ-CON-3, 4.1.1) |
| Timezone | `Pacific/Auckland` | DST oficial de Wellington |
| Late spike label | `late_spike_l1 = (k_eod != k_cp)` | inteiros, sem ambiguidade de Q (4.4 + 9) |
| `prob_dist` baselines | empirico condicional `(month, cp, k_cp)` | sem gaussiana cosmetica (8 - tabela) |
| `prob_dist` ML | softmax band-aware com `tau` congelado | 8.1.1 |
| Suporte K | derivado de climo+NWP percentis +/- 2 | 4.5.1 |
| NWP selection v1 | latest run <= cp - 30min; valid_time = climo Tmax_hour | 4.5.2 |
| Shadow execution | `taker_at_quote`, fee=200bps, sizing=1 unit | REQ-MET-5, 10.1 |
| Tuning protocol | nested walk-forward; tunar so thresholds operacionais | REQ-MET-6, 10.2 |
| Core preferido | NWP + residual | discutido na secao 25 do v1 |
| Regimes | GMM 6-8 fixo | evitar clusters ad-hoc (secao 21.10 v1) |

## 16. Decisoes em aberto (rastreadas em requirements `OPN-*`)

- Fonte NWP (ECMWF / GFS / blending) - **OPN-5**.
- Validacao binaria do contrato com resolver Polymarket - **OPN-1**.
- Cutoffs operacionais "NO caro" - **OPN-3** (a aprender).

---

## 17. Riscos e mitigacoes

| Risco | Mitigacao |
|-------|-----------|
| Leakage por janela `closed='right'` | regra unica em `core/features/rolling.py`; auditoria 5.5 fase 2 detecta |
| Nowcaster disfarcado | gates pre-registrados (REQ-AUD-2) e variant "no temperature" |
| DST quebra Tmax(D0) | testes especificos em `tests/unit/test_dst.py` (REQ-CON-4) |
| Soft-fail mascarando ausencia de forecasts | exit code != 0; alerta de `n_forecasts_emitted == 0` |
| Calibrador miope | janela >= 12 meses obrigatoria (secao 16 v1, REQ - secao 21.11) |
| Drift de NWP / mudanca de modelo upstream | hash do `model_id` NWP em snapshots; relatorio mensal `reports/nwp_health.md` |
| Auditoria contaminando codigo | reverse-import guard (REQ-AUD-3) |
| Overfitting de thresholds | funcao-objetivo congelada (REQ-DEC-3) |

---

## 19. Fase 4 - NWP source decisao + HRES vs multi-model ablation

> Contexto: OPN-5 fechado em `contracts/nwp_source.md v1.0` apos analise de cobertura
> da Open-Meteo. Detalhes operacionais aqui.

### 19.1 Provider e endpoints

- Open-Meteo `historical-forecast-api` (backfill stitched) e `single-runs-api`
  (causal estrito por `run_time_utc`).
- v1 launch set: **ECMWF IFS HRES** + **NCEP GFS** (ambos cobrem todas as 3 splits).
- Scale-up para 4 modelos (+ UKMO + ICON Global) so com bump de `NWP_SOURCE_VERSION`
  apos v1 passar gates de Fase 4 (REQ-MET-4 + REQ-AUD-2).

### 19.2 Pre-registered ablation: HRES vs multi-model (reforco D do open-meteo)

Estacoes costeiras/topograficas como NZWN podem nao se beneficiar de hi-res por
representatividade do gridbox vs ponto. Pre-registramos 5 variantes em Fase 4:

| Variante | Conteudo |
|---|---|
| A. HRES-only | apenas ECMWF IFS HRES como input de NWP residual learning |
| B. GFS-only | apenas NCEP GFS |
| C. UKMO-only | (so executa apos scale-up para 4 modelos) |
| D. ICON-only | (so executa apos scale-up para 4 modelos) |
| E. Multi-model blend | media simples dos modelos disponiveis no CP + spread + residual learning |

**Criterio de aceite para "HRES-only" como pilar principal:**
- ganho em bracket-match em `>= 2/3 splits` vs cada uma das outras variantes,
- ganho excede IC95% bootstrap paired,
- nao regride RPS / ECE.

Se HRES-only nao satisfaz: o **default e Multi-model blend (variante E)** e HRES vira
"mais um membro" do ensemble. Decisao gravada em `reports/phase4_nwp_ablation.md`
com `NWP_SOURCE_VERSION` na header.

### 19.3 Anti-overengineering rules (reforco)

- **Sem regridding em v1.** Usar o valor que Open-Meteo retorna para `lat=-41.3272,
  lon=174.8053` (NZWN); auditar consistencia (variacao de retorno entre endpoints
  por timestamp) em T-OPN-5a.
- Selecao de gridcell deixa para v1.1 (`grid_cell_selection=nearest|sea|land`).
- Sem ensemble weighting tunavel em v1; media simples ate v1.1.

### 19.4 Open-Meteo stitching leakage - validacao empirica obrigatoria (T-OPN-5a)

Conforme `contracts/nwp_source.md` secao "Cross-check obligation": antes de promover
Phase 4 para "ready", rodar HFAPI vs Single Runs ECMWF no overlap 2024-03..2025-12
e validar bracket-match / RPS / ECE / per-split sanity.

---

## 18. Compatibilidade futura (multi-cidade)

Embora o escopo v1 seja NZWN, a arquitetura permite replicacao:
- todo codigo agnostico vive em `core/`,
- configs e calibradores locais em `<station_code>/` (ex.: `nzwn/`, futuro `nzaa/`),
- contratos sao por-cidade quando o resolver muda; default global onde aplicavel.

Antes de habilitar nova cidade: criar `<code>/config/`, treinar regimes e calibradores, repetir auditoria forense completa.
