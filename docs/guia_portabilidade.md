# Guia de Portabilidade, Reproducao e Licoes Aprendidas

> Como reconstruir este sistema (forecaster intraday de Tmax inteiro com causalidade
> CP-aware, confianca calibrada e auditoria anti-nowcaster) para OUTRA cidade/estacao,
> ou como um SEGUNDO sistema para a mesma cidade. Idioma PT-BR, ASCII (REQ-OPS-2).
>
> **Objetivo deste doc:** transformar as dificuldades que ja pagamos (sobretudo o
> campo minado de *sourcing* de NWP na Fase 4) em um playbook, pra que a proxima
> implementacao NAO refaca a descoberta do zero. Leia a secao 2 ANTES de escrever
> qualquer codigo de ingestao - e onde mora 80% do retrabalho evitavel.
>
> **Como usar / como estender:** o codigo ja e modular - a parte especifica de
> estacao (climatologia, config, fuso) e ADAPTADA, nao reescrita. Este guia NAO e um
> plano de refatoracao multi-cidade; e um DIARIO DE PROBLEMAS. Cada sistema novo tem
> suas proprias validacoes e armadilhas: ao enfrentar uma, registre-a na secao 7 no
> formato sintoma -> diagnostico -> solucao, pra que o proximo nao tropece nela.

---

## 0. Resumo executivo das licoes caras

1. **Disponibilidade de NWP e especifica de local E de tempo, e MENTE via HTTP 200.**
   Um endpoint pode responder 200 com grade horaria VAZIA. "Servidor respondeu" nunca
   e "dado existe". Toda fonte tem que ser provada empiricamente, por ano, com t2m
   nao-nulo de verdade - nunca assumida a partir de doc.
2. **Causalidade e o jogo inteiro.** `run_time_utc <= cp_utc - safety_margin`. Series
   "costuradas" (stitched/HFAPI) vazam o futuro; so um run unico (single-run / GRIB de
   ciclo especifico) e causal. Misturar os dois corrompe silenciosamente o veredito.
3. **A informatividade do gridpoint tem que ser provada antes de investir no pipeline.**
   Celula 0.25deg sobre o mar pode amortecer o sinal de terra. Probe barato (minutos)
   evita semanas de pipeline inutil.
4. **Conversao de unidade e superficie de bug.** GRIB2 entrega Kelvin nativo; Open-Meteo
   ja entrega Celsius. Trocar de fonte = revalidar K->C.
5. **eccodes/GRIB ficam OFFLINE.** Nunca no runtime/CI: contaminam o gate de
   determinismo (dois treinos tem que ser byte-identicos).
6. **Anti-gaming e regra dura.** Pre-registrar a arvore de decisao com sha256, e NUNCA
   afrouxar threshold depois de ver resultado. Trocar de branch por indisponibilidade
   de fonte e permitido SE o porque estiver registrado na pre-registracao.

---

## 1. Mapa de acoplamento: o que e config vs o que esta hard-coded

### 1.1 Ja e data-driven (troca por arquivo, sem mexer em codigo)

- `nzwn/config/station.yaml` - `icao`, `name`, `lat`, `lon`, `elevation_m`, `tz`,
  `cp_set_utc`, `cp_operational_utc`, limites de plausibilidade de temperatura,
  regra de `day_complete`.
- `nzwn/config/model.yaml` - `prob_dist.tau`/`mode`, `nwp.safety_margin_minutes`,
  ids de modelo NWP (contrato config<->codigo validado por `load_nwp_model_specs`).

### 1.2 Ainda hard-coded (PRECISA generalizar para multi-cidade)

> Hoje sao ~26 arquivos com `NZWN` / `-41.32` / `Pacific/Auckland` literais. Para um
> SEGUNDO sistema isolado (caso desta pergunta) basta copiar o repo e trocar os pontos
> abaixo; para multi-cidade no mesmo repo, e preciso parametrizar.

| Onde | O que esta fixo | Como generalizar |
|---|---|---|
| `scripts/gfs_grib_decode.py` | `NZWN_LAT`, `NZWN_LON` | ler de `station.yaml` (passar lat/lon como args) |
| `scripts/gfs_s3_backfill.py` | `station="NZWN"`, gridpoint | idem; aceitar `--station` |
| `scripts/opn5a_*.py` | `cfg.icao`, janela de overlap | ler do config + datas por arg |
| `core/baselines/climatology.py` | `tz_name` default `Pacific/Auckland` | exigir tz do config |
| `core/labels/tmax.py`, `core/ingest/iem_csv.py` | defaults de tz/estacao | idem |
| `audits/run_h0_audit.py` | thresholds dos gates | sao do contrato; versionar por estacao |

**Regra pratica:** nenhum lat/lon/tz/icao novo deve nascer no codigo. Se vc se pegar
digitando coordenada num `.py`, ela pertence ao `station.yaml`.

---

## 2. Playbook de sourcing de NWP (onde mora 80% do retrabalho)

> Esta secao e o coracao do guia. A historia real desta fase: comecamos achando que
> a fonte estava resolvida (HFAPI stitched), descobrimos que ela vaza, tentamos
> single-runs, descobrimos que cada provedor/modelo tem janela de disponibilidade
> diferente e que HTTP 200 mente. Siga a arvore abaixo e vc economiza semanas.

### 2.1 Conceitos que voce PRECISA separar

- **Stitched / Historical Forecast (HFAPI):** serie continua "costurada" de varios
  runs, cada hora vinda do run mais fresco. Otima para *features* de incerteza, mas
  **NAO causal**: a hora `t` pode ter vindo de um run emitido depois do seu CP. Usar
  como ancora = vazamento.
- **Single-run / ciclo:** um unico run identificado por `run_time_utc`. Causal SE
  `run_time_utc <= cp_utc - safety_margin`. E o unico aceitavel como ancora.
- **Archive vs Forecast:** "archive" (reanalise) usa observacoes futuras -> proibido.
  Tem que ser forecast *historico* (o que o modelo dizia naquele momento).

### 2.2 Arvore de decisao de fonte (rode NESTA ordem, por modelo e por ano)

```
Para cada (modelo, ano do split):
  1. PROBE DE EXISTENCIA: peca um single-run causal e cheque t2m NAO-NULO de verdade.
     - 200 com grade vazia = FONTE NAO SERVE aquele periodo. Nao confie no status.
     - registre: primeiro mes com dado real (ex.: ECMWF causal so >= 2024-03).
  2. SE existe via API causal (single-runs): use direto. Fim.
  3. SE NAO existe via API (ex.: GFS single-run no Open-Meteo = 0 t2m sempre):
     - a fonte causal so existe como GRIB2 bruto (ex.: AWS noaa-gfs-bdp-pds).
     - va para a secao 2.4 (pipeline GRIB offline).
  4. SE nenhuma fonte causal existe para aquele ano:
     - branch pre-registrado de "criterion-fail": dropar o split OU trocar de ancora,
       SEMPRE documentando o porque na pre-registracao (nao e afrouxar threshold).
```

### 2.3 PROBE DE INFORMATIVIDADE (gate barato, antes de investir)

Antes de construir qualquer pipeline pesado (GRIB), responda: **o gridpoint do modelo
nessa cidade carrega o sinal de Tmax da estacao, ou a celula esta sobre o mar e
amortece?** Para estacao costeira/ilha isto e critico.

- Script de referencia: `scripts/gfs_informativeness_probe.py`.
- Metodo: max diario do t2m do modelo (mesmo via HFAPI, que aqui serve por ser um
  limite superior otimista) vs Tmax observado; reporte pearson/spearman/slope por ano.
- Criterio de viabilidade: pearson alto (>~0.8) E slope ~1 (sem amortecimento). Vies
  medio constante NAO reprova (a ancora entra como anomalia e o residual aprende).
- Resultado NZWN (guardado em `reports/gfs_probe.json`): GFS pooled pearson 0.953,
  slope 1.03, vies ~-1C. Celula costeira NAO matou o sinal. Por isso a Opcao 1 (GFS)
  foi viavel. **Numa cidade nova, este probe pode REPROVAR - e ai vc muda de modelo,
  nao de codigo.**

### 2.4 Pipeline GRIB2 offline (quando a fonte causal so existe como GRIB bruto)

Padrao implementado (reaproveitavel), com os guardrails que custaram caro:

1. **Byte-range via `.idx`.** Nunca baixe o campo inteiro (~500 MB). Leia o sidecar
   `.idx`, ache a mensagem da variavel (ex.: `TMP:2 m above ground`), e faca um
   Range-GET so daquela mensagem (centenas de KB). Logica isolada e SEM eccodes em
   `core/ingest/grib_idx.py` (testavel em CI).
2. **eccodes OFFLINE, import local.** O decoder (`scripts/gfs_grib_decode.py`) importa
   eccodes DENTRO da funcao, e nunca e importado por `core/`. Decodifica direto da
   memoria (`codes_new_from_message`) - nada de temp file (no Windows o unlink corre
   com o handle aberto -> WinError 32).
3. **Gridpoint = nearest-cell, SEM regridding** (design v1). Registre lat/lon que o
   modelo retornou e a distancia (haversine) ao ponto pedido. Cheque < ~20 km.
4. **K->C explicito** e spot-check de range plausivel para a estacao/estacao-do-ano.
5. **Proveniencia obrigatoria** (`provenance.json`): versao do eccodes, variavel,
   regra de interpolacao, regridding=none, regra K->C, tratamento de vies (documentado,
   NAO corrigido), byte-ranges, faixa de datas, n de mensagens.
6. **Saida no schema canonico** (`run_time_utc, valid_time_utc, lead_h, t2m_c, ...`)
   particionada por ano/mes + manifesto SHA256, sob um `endpoint` proprio (ex.:
   `s3_grib`) pra nao se misturar com `hfapi`. Assim os seletores causais existentes
   (`select_nwp_ensemble`, `select_max_trajectory_anchor`) consomem sem mudanca.

### 2.5 Ancora: max-de-trajetoria (nao hora-unica)

A ancora NAO e o t2m numa hora climatologica fixa, e o **MAX sobre uma janela forward**
(distribuicao da hora-do-Tmax por mes) do MESMO run causal. Robusto a pico sazonal
adiantado/atrasado. Implementado em `core/features/nwp.py::select_max_trajectory_anchor`.
Ao portar: a janela vem da climatologia de hora-do-Tmax da nova cidade
(`fit_tmax_hour_climatology`), nao de um numero magico.

### 2.6 Homogeneidade de fonte entre splits (armadilha sutil)

Se o split A usa modelo X como ancora e o split B usa modelo Y, o residual aprende um
offset especifico-de-modelo e a evidencia do split A fica confundida com a troca de
modelo. **Prefira a MESMA fonte causal em todos os splits** (foi por isso que GFS-em-
todos venceu ECMWF-so-em-2). Se for impossivel manter homogeneidade, padronize a ancora
como anomalia da climatologia do PROPRIO modelo por split (correcao model-agnostica) e
documente a assimetria.

---

## 3. Passo-a-passo para uma estacao NOVA

> Pre-requisito: um CSV historico de observacoes (no NZWN veio do IEM ASOS, cadencia
> 30 min). Sem >= ~3-4 anos de obs nao da pra ter splits walk-forward decentes nem
> climatologia estavel (a climatologia de hora-do-Tmax exige >= 365 dias de treino).

1. **Config.** Criar `<estacao>/config/station.yaml` (icao, lat, lon, tz, cp_set_utc,
   plausibilidade, day_complete) e `model.yaml` (tau, safety_margin, ids de modelo).
   NAO copiar coordenada pra dentro de `.py`.
2. **Ingestao de obs + labels.** Adaptar a fonte de obs; gerar `tmax_int`,
   `day_complete`, `tmax_ts_local`. Validar `day_complete` (kill se imputacao > 0.5%).
3. **Baselines (Fase 2/3).** Persistencia, climatologia, Ridge band-aware. Rodar
   `scripts/phase3_evaluate.py` adaptado pra estacao. Esses ja sao o piso a vencer.
4. **SOURCING DE NWP (Fase 4) - use a secao 2 inteira:**
   - 2.2 arvore de fonte por modelo/ano -> descobrir o que e causal e desde quando.
   - 2.3 probe de informatividade -> decidir o modelo-ancora (PODE reprovar e mudar
     a escolha; e barato).
   - 2.4 pipeline GRIB offline so se a fonte causal exigir.
   - Recalcular `CAUSAL_RUN_HOUR`/`LEADS` para o novo fuso (secao 1.3!).
5. **Pre-registracao com dentes (anti-gaming).** Escrever
   `contracts/phase4_preregistration.md` com a arvore de decisao, seeds, fronteiras de
   fold e thresholds; computar sha256 e travar em `core/eval/preregistration.py`. O
   evaluator recusa rodar se o hash em runtime != hash commitado.
6. **Avaliacao + gates.** `scripts/phase4_evaluate.py`: ablacao pareada
   (LGBM(obs+NWP) - LGBM(obs-only), CI95 lo>0 em >=2/3 splits) + bateria anti-nowcaster
   (REQ-AUD-2). Relatorio ESTRATIFICADO POR LEAD, nunca numero global unico.
7. **Cross-check de fonte.** Equivalente ao `opn5a_*`: validar que o resultado nao e
   artefato de um modelo so.
8. **Determinismo.** `tests/unit/test_determinism.py`: dois treinos -> sha256 identico.
   Garantir que eccodes/GRIB NAO entrou no grafo de import do runtime.

---

## 4. Disciplina anti-gaming (inegociavel)

- Gates e thresholds sao CONGELADOS antes de ver resultado. Nunca mexer num gate
  congelado pra ele passar.
- Toda mudanca de gate/contrato/threshold exige bump de versao + changelog +
  re-execucao da auditoria H0 (5 etapas no README do spec).
- Trocar de branch por indisponibilidade de fonte (ex.: dropar split, trocar ancora)
  e PERMITIDO **se** o porque estiver registrado na pre-registracao. Isso e auditavel,
  nao e afrouxar.
- O recomputo do sha256 da pre-registracao e o ULTIMO passo, depois da fonte validada
  empiricamente. Congelar antes de validar = pre-registracao que se move = sem valor.

---

## 5. Checklist de portabilidade (copie e marque)

```
[ ] station.yaml + model.yaml criados; ZERO coordenada nova em .py
[ ] obs ingeridas; day_complete validado; climatologia >= 365 dias de treino
[ ] baselines (persistencia/climo/Ridge) rodando e medidos
[ ] CAUSAL_RUN_HOUR + LEADS recalculados para o fuso da nova cidade (secao 1.3)
[ ] arvore de fonte (2.2) percorrida por modelo/ano; primeiro mes causal anotado
[ ] probe de informatividade (2.3) rodado; modelo-ancora escolhido por evidencia
[ ] (se GRIB) pipeline offline com byte-range + provenance.json + K->C validado
[ ] eccodes/GRIB fora do runtime/CI (gate de determinismo intacto)
[ ] ancora = max-de-trajetoria com janela da climatologia de hora-do-Tmax local
[ ] mesma fonte causal em todos os splits (ou anomalia-da-propria-climo documentada)
[ ] pre-registracao com sha256 travado; evaluator falha se hash divergir
[ ] ablacao pareada CI95 lo>0 em >=2/3; relatorio estratificado por lead
[ ] cross-check de fonte (anti-artefato-de-modelo)
[ ] disciplina anti-gaming respeitada; mudancas versionadas com changelog
```

---

## 6. Indice de artefatos de referencia (onde olhar no NZWN)

| Tema | Arquivo |
|---|---|
| Requisitos formais (REQ-*), gates, pendencias | `.kiro/specs/.../requirements.md` |
| Arquitetura, schemas, decisoes congeladas | `.kiro/specs/.../design.md` |
| Fases, entregaveis, kill criteria | `.kiro/specs/.../implementation-plan.md` |
| Contrato de fonte NWP (versionado) | `contracts/nwp_source.md` |
| Pre-registracao com dentes | `contracts/phase4_preregistration.md` |
| Probe de informatividade | `scripts/gfs_informativeness_probe.py` + `reports/gfs_probe.json` |
| Logica .idx (eccodes-free) | `core/ingest/grib_idx.py` |
| Decoder GRIB offline | `scripts/gfs_grib_decode.py` |
| Backfill S3 + probe de validacao | `scripts/gfs_s3_backfill.py` |
| Ancora max-de-trajetoria | `core/features/nwp.py` |
| Cross-check de fonte | `scripts/opn5a_hfapi_vs_single_runs.py` |
| Runbook operacional Opcao 1 | `reports/phase4_option1_runbook.md` |
| Atribuicao de fontes de dados | `references/legacy/data_sources.md` |

---

## 7. Diario de problemas (sintoma -> diagnostico -> solucao)

> Casos REAIS desta implementacao (NZWN). Ao portar para outra estacao, ADICIONE os
> seus aqui no mesmo formato. Este e o ativo mais reaproveitavel do guia: cada entrada
> e uma armadilha que alguem ja pagou pra descobrir.

### P-01 - HTTP 200 com grade horaria vazia
- **Sintoma:** endpoint single-runs responde 200, estrutura OK (168 linhas, 1 run,
  leads 0..167), parece valido. Mas o forecast nao melhora / da ruido.
- **Diagnostico:** `t2m` vinha NULO em todas as linhas. "200" provava alcance da API,
  nao existencia de dado para aquele periodo/local.
- **Solucao:** validar SEMPRE t2m nao-nulo de verdade, por ano, antes de confiar numa
  fonte. Nunca derivar disponibilidade do status HTTP nem da doc do provedor.

### P-02 - Open-Meteo nao serve GFS single-runs para o ponto
- **Sintoma:** todas as combinacoes de model-id GFS (gfs_global, gfs_seamless, gfs025,
  ncep_gfs025, gfs013) retornavam 0 t2m nao-nulo em todos os anos, apesar de 200.
- **Diagnostico:** o provedor simplesmente nao expoe GFS single-run para NZWN; a fonte
  causal de GFS so existe como GRIB2 bruto no S3 (noaa-gfs-bdp-pds).
- **Solucao:** quando a API causal nao serve, cair para o GRIB2 do upstream (secao 2.4).
  E por isso que "GFS-everywhere" custou um pipeline GRIB de 3 anos, nao so de 2023.

### P-03 - Janela de disponibilidade difere por modelo
- **Sintoma:** ECMWF single-run causal vazio em fev/2024, cheio em mar/2024.
- **Diagnostico:** cada modelo/provedor tem um primeiro-mes-causal diferente (ECMWF
  causal so >= 2024-03 no Open-Meteo). Assumir cobertura uniforme quebra splits.
- **Solucao:** percorrer a arvore (2.2) por modelo E por ano; anotar o primeiro mes
  real. Foi o que tornou ECMWF inviavel como ancora homogenea nos 3 splits.

### P-04 - WinError 32 ao decodificar GRIB de temp file
- **Sintoma:** decode via `codes_grib_new_from_file` num NamedTemporaryFile -> erro de
  arquivo em uso no unlink (Windows).
- **Diagnostico:** o unlink do temp file corria com o handle ainda aberto pelo eccodes.
- **Solucao:** decodificar direto da memoria com `codes_new_from_message(bytes)`. Sem
  temp file. (Ja aplicado em `scripts/gfs_grib_decode.py`.)

### P-05 - Longitude 0..360 vs -180..180
- **Sintoma:** risco de gridpoint errado / distancia absurda ao pedir o ponto.
- **Diagnostico:** GFS usa longitudes 0..360; o ponto pedido vinha em -180..180.
- **Solucao:** normalizar `req_lon = lon % 360` ao consultar, e reportar de volta em
  -180..180 (`((glon+180)%360)-180`) so para comparacao humana. Validar distancia<20km.

### P-06 - eccodes ameacava o gate de determinismo
- **Sintoma:** colocar GRIB no pipeline poderia tornar os dois treinos nao byte-identicos.
- **Diagnostico:** libs nativas (eccodes) no grafo de import do runtime introduzem
  variabilidade e dependencia de ambiente; o gate exige sha256 identico.
- **Solucao:** eccodes SO offline, import local, nunca importado por `core/`. O runtime
  le apenas Parquet ja decodificado. Logica .idx isolada (eccodes-free) e testavel em CI.

### P-07 - ASCII guard quebra com saida unicode
- **Sintoma:** prints de DataFrame polars (bordas de caixa unicode) violavam o ASCII guard.
- **Diagnostico:** REQ-OPS-2 exige ASCII em logs/CLIs; o pretty-printer emite unicode.
- **Solucao:** `PYTHONIOENCODING=ascii` + evitar imprimir frames; montar saida texto a mao.

### P-08 - import de modulo irmao em scripts/ (nao-pacote)
- **Sintoma:** `py -3 scripts/gfs_s3_backfill.py` -> ModuleNotFoundError em
  `from scripts.gfs_grib_decode import ...`.
- **Diagnostico:** `scripts/` nao tem `__init__.py` e e excluido no pyproject; na
  invocacao direta o pacote `scripts` nao existe.
- **Solucao:** import com fallback (try `scripts.x` / except `x`) para funcionar tanto
  em `-m scripts.x` quanto na invocacao direta.

### 1.3 Premissa de calendario embutida (ATENCAO ao portar)

O backfill assume que **o run 18Z de (d-1) e o ciclo causal para todos os CPs de
{20,21,22,23} UTC** do dia local `d`. Isso vale para a longitude/tz de Wellington
(NZST/NZDT). Para outra cidade com outro fuso, o ciclo causal pode ser outro (00/06/12Z)
e os leads forward podem cair em outras horas de previsao. **Recalcule** `CAUSAL_RUN_HOUR`
e `LEADS` em `scripts/gfs_s3_backfill.py` a partir do novo `cp_set_utc` + tz + a
janela de hora-do-Tmax local da nova climatologia. Esta e a armadilha de portabilidade
mais sutil do sistema.
