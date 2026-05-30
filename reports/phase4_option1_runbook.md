# Runbook - Fase 4 Opcao 1 (ancora GFS causal via S3+eccodes)

> Documento operacional. Execute fora do Claude Code (terminal proprio), onde NAO
> existe o bloqueio do "bash classifier". Ordem ESTRITA: o probe (Passo 3) e um GATE -
> nada de decode em massa nem recomputo de sha256 antes dele passar (guardrail do
> review: validar gridpoint + K->C ANTES de decodificar 3 anos).
>
> Idioma ASCII (convencao REQ-OPS-2). Shell: bash no Windows, launcher `py -3`.

## Contexto (decisao ja travada)

- update.txt = GO firme na **Opcao 1**: GFS como ancora homogenea nos 3 splits
  (2023/2024/2025), decodificada OFFLINE do S3 `noaa-gfs-bdp-pds`.
- Gate (a) ja PASSOU e esta em `reports/gfs_probe.json`: GFS pooled pearson 0.953,
  slope 1.03, sem amortecimento maritimo, vies frio ~-1C (documentado, NAO corrigido).
- Open-Meteo NAO serve GFS single-runs (0 t2m em todos os anos) -> por isso o GFS
  causal so existe via GRIB2 do S3. ECMWF causal so existe a partir de 2024-03 e
  entra aqui apenas como cross-check (teto diagnostico), nao como ancora.
- eccodes/cfgrib ficam OFFLINE: nunca no runtime/CI (contaminariam o gate de
  determinismo que exige dois treinos byte-identicos).

## TL;DR (sequencia de comandos)

```bash
# a partir da raiz do repo: D:/Downloads/Wellington
py -3 -m pip install -e .                                  # sanity (se ainda nao)
py -3 -m pip install eccodes                               # tooling OFFLINE
py -3 -c "import eccodes; print(eccodes.codes_get_api_version())"
py -3 -m pytest tests/unit/test_grib_idx.py -q             # 7 passed esperados
py -3 scripts/gfs_s3_backfill.py --probe 2023-06-01        # <-- O GATE
# SE o probe passar (ver criterios abaixo), entao:
py -3 scripts/gfs_s3_backfill.py --start 2023-01-01 --end 2023-12-31
py -3 scripts/gfs_s3_backfill.py --start 2024-01-01 --end 2024-12-31
py -3 scripts/gfs_s3_backfill.py --start 2025-01-01 --end 2025-12-31
py -3 scripts/opn5a_ecmwf_backfill.py --start 2024-03-01 --end 2025-12-31
py -3 scripts/opn5a_hfapi_vs_single_runs.py
```

---

## Passo 1 - Instalar eccodes (tooling offline)

```bash
py -3 -m pip install eccodes
py -3 -c "import eccodes; print(eccodes.codes_get_api_version())"
```

Esperado: imprime uma versao tipo `2.4x.x` sem erro.

Se `import eccodes` falhar com "library not found" (Windows sem a libeccodes C):

```bash
py -3 -m pip install eccodeslib findlibs
py -3 -c "import eccodes; print(eccodes.codes_get_api_version())"
```

(O wheel binario moderno ja embute a lib; o fallback `eccodeslib` resolve os casos
em que nao embute.)

## Passo 2 - Testes unitarios do .idx (NAO precisa eccodes)

```bash
py -3 -m pytest tests/unit/test_grib_idx.py -q
```

Esperado: `7 passed`. Validam construcao de key S3, parse do `.idx`, selecao da
mensagem TMP:2m e header de byte-range. Sao eccodes-free de proposito (CI-safe).

## Passo 3 - PROBE de uma data (O GATE - guardrail do review)

```bash
py -3 scripts/gfs_s3_backfill.py --probe 2023-06-01
```

O que faz: baixa SO a mensagem TMP:2m do run 18Z de 2023-06-01 (leads f000..f013)
via byte-range do `.idx`, decodifica no gridpoint do NZWN e compara com o HFAPI ja
em disco. NAO escreve nada.

Saida esperada (valores aproximados):
- `requested gridpoint: lat=-41.3272, lon=174.8053`
- `returned gridpoint:  lat=-41.2500, lon=174.7500  (distance=~9.7 km)`
  (celula 0.25deg mais proxima; distancia tem que ser < 20 km)
- `TMP:2m K->C range: min~6C max~17C` (junho = inverno em Wellington; o probe de
  2023-06-01 observou ~13.4..15.9C - tem que cair em [-10,40]C; se vier ~280 a
  ~290, a conversao K->C falhou)
- bloco "GRIB vs HFAPI ... diff": diferencas pequenas (ordem de 0 a 2C)

CRITERIOS DE APROVACAO (impressos no fim):
- `K->C plausibility ([-10,40]C): PASS`
- `gridpoint distance < 20km: PASS`
- exit code 0

Se QUALQUER um falhar: PARE. Nao rode o decode em massa. Cole a saida completa de
volta pra mim - provavelmente e (a) gridpoint errado (lon 0-360 vs -180..180),
(b) K->C, ou (c) selecao da mensagem no `.idx`. Eu corrijo o decoder antes de seguir.

## Passo 4 - Decode em massa GFS 2023-2025 (offline, demorado)

So execute se o Passo 3 passou. Rodar por ano (cada ano = ~365 runs x 14 leads =
~5100 GETs de poucos KB; minutos a dezenas de minutos por ano, depende da rede):

```bash
py -3 scripts/gfs_s3_backfill.py --start 2023-01-01 --end 2023-12-31
py -3 scripts/gfs_s3_backfill.py --start 2024-01-01 --end 2024-12-31
py -3 scripts/gfs_s3_backfill.py --start 2025-01-01 --end 2025-12-31
```

Saida em disco:
- `artifacts/raw/nwp/NZWN/ncep_gfs_global/s3_grib/<ano>/<mes>.parquet`
- `artifacts/raw/nwp/NZWN/ncep_gfs_global/s3_grib/provenance.json`
  (eccodes ver, gridpoint, interpolacao=nearest_cell, regridding=none, regra K->C,
  tratamento do vies frio = documentado/nao-corrigido, byte-ranges)
- linhas novas em `artifacts/raw/nwp/manifest.jsonl` (SHA256 por particao)

Idempotente: reexecutar uma faixa nao duplica (dedup por
model+endpoint+run_time_utc+valid_time_utc). Se cair a rede no meio, e so rodar a
mesma faixa de novo.

## Passo 5 - Backfill ECMWF Single Runs (cross-check / teto)

```bash
py -3 scripts/opn5a_ecmwf_backfill.py --start 2024-03-01 --end 2025-12-31
```

~670 runs no endpoint single-runs-api.open-meteo.com. Saida em
`artifacts/raw/nwp/NZWN/ecmwf_ifs_hres/single_runs/...`. NAO e ancora - serve so pra
corroborar que o resultado ancorado em GFS nao e artefato de um modelo so.

## Passo 6 - Cross-check T-OPN-5a (max-de-trajetoria)

```bash
py -3 scripts/opn5a_hfapi_vs_single_runs.py
```

Compara HFAPI vs Single Runs ECMWF na agregacao max-de-trajetoria, pelos 4 criterios
do contrato. Emite `reports/opn5a_cross_check.md` + `reports/opn5a_verdict.json`.

NOTA esperada: o criterio 4 le `reports/phase4.json`, que ainda nao existe nesta
etapa -> vai reportar `phase4_json_absent` e adiar o criterio 4. Isso e ESPERADO; o
criterio 4 fecha depois que eu religar o evaluator e ele rodar (vide "O que eu faço
depois").

---

## O que me mandar de volta (pra eu continuar)

Cole no chat:
1. A saida COMPLETA do Passo 3 (probe) - e o gate, e o mais importante.
2. O resultado do Passo 2 (`pytest`).
3. Se ja rodou 4-6: o conteudo de
   `artifacts/raw/nwp/NZWN/ncep_gfs_global/s3_grib/provenance.json` e de
   `reports/opn5a_cross_check.md`.

Pode disparar os Passos 4-6 (longos) em paralelo enquanto me manda o resultado do
Passo 3 - eu comeco a religar o evaluator com base no probe aprovado, sem esperar o
decode terminar.

## O que eu faço depois (no Claude Code, NAO e sua tarefa)

Somente APOS o probe (Passo 3) passar:
1. Religar `scripts/phase4_evaluate.py` para usar a ancora max-de-trajetoria
   (`select_max_trajectory_anchor`) lendo o endpoint `s3_grib` do GFS, no lugar do
   atual `nwp_t2m_at_cp_c` so-HFAPI.
2. Atualizar `contracts/nwp_source.md` (criterio 4: 2023 agora tem fonte CAUSAL GFS,
   nao mais "HFAPI-only") com bump de versao + changelog.
3. Atualizar o bloco canonico de `contracts/phase4_preregistration.md` (registrar
   Opcao 1 + evidencia do probe + regras de gridpoint/K->C/vies) e RECOMPUTAR
   `COMMITTED_SHA256` em `core/eval/preregistration.py` no mesmo commit
   (`py -3 -m core.eval.preregistration` imprime o hash novo).
4. Rodar `py -3 scripts/phase4_evaluate.py` -> `reports/phase4.md` estratificado por
   lead + `h0_verdict.json`; e entao o cross-check fecha o criterio 4.

Esse recomputo de sha256 e deliberadamente o ULTIMO passo: a pre-registracao so e
"congelada de novo" depois que a fonte foi validada empiricamente - sem afrouxar
nenhum threshold depois de ver resultado.

## Rede autorizada / seguranca

- GFS: `https://noaa-gfs-bdp-pds.s3.amazonaws.com` (HTTPS anonimo, sem credencial AWS).
- ECMWF: `single-runs-api.open-meteo.com`.
- Nada de secrets em commit (.env/credentials). eccodes/cfgrib so offline.
