# Code Review 29 - Caminho GFS S3 / Fase 4 Opcao 1

Escopo: codigo do backfill causal GFS via S3+eccodes e cross-checks da Fase 4.
Motivacao: a execucao do runbook foi abandonada porque o decode em massa estava
lento demais. Este review prioriza a causa-raiz de performance e depois
corretude/arquitetura. Texto em ASCII (REQ-OPS-2). Nenhum codigo foi alterado.

Arquivos revisados:
- scripts/gfs_s3_backfill.py
- scripts/gfs_grib_decode.py
- core/ingest/grib_idx.py
- core/ingest/nwp.py (_write_partitioned, read_snapshots, select_nwp_v1)
- core/ingest/nwp_client.py
- scripts/opn5a_ecmwf_backfill.py
- scripts/opn5a_hfapi_vs_single_runs.py

Estado funcional confirmado nesta sessao: eccodes 2.47.0 OK; testes
tests/unit/test_grib_idx.py 8 passed; probe 2023-06-01 PASS (gridpoint 9.75 km,
K->C 13.38..15.90 C). O probe so passou apos corrigir um bug de plataforma no
decoder (ver P1). O bulk de 3 dias (2023-06-01..03) escreveu Parquet+provenance
corretamente.

---

## 1. Performance (causa-raiz da lentidao)

### PERF-1 (CRITICO) - Cliente httpx recriado a cada requisicao, sem keep-alive

`scripts/gfs_grib_decode.py`: `_http_get_bytes` e `_http_get_text` abrem um
`httpx.Client()` novo por chamada (via `with httpx.Client(...) as client`). Cada
GET paga handshake TCP+TLS completo contra `noaa-gfs-bdp-pds.s3.amazonaws.com`.

Volume por ano: ~365 runs x 14 leads x 2 GETs (1 `.idx` + 1 byte-range) = ~10.220
requisicoes/ano, ~30.660 para 2023-2025. Todas sequenciais e cada uma com TLS
do zero. Esse e o item dominante do tempo de parede.

Correcao recomendada: um unico `httpx.Client` reaproveitado (connection pool +
keep-alive) passado adiante por `fetch_tmp_2m_message` -> `_decode_run` -> `_bulk`.
Ganho tipico 3-10x so com reuso de conexao.

### PERF-2 (CRITICO) - Decode estritamente sequencial, sem concorrencia

`_decode_run` (gfs_s3_backfill.py) percorre f000..f013 em serie; `_bulk` percorre
os runs em serie. Sao requisicoes I/O-bound independentes - candidato direto a
concorrencia (httpx.AsyncClient, ou ThreadPoolExecutor com cliente compartilhado).
Paralelizar os 14 leads de um run, e/ou alguns runs ao mesmo tempo, reduz o tempo
de parede de forma multiplicativa sobre o PERF-1. Atencao a manter a politesse com
o S3 (limite de concorrencia + jitter) ja que o endpoint e anonimo/compartilhado.

### PERF-3 (ALTO) - Amplificacao de escrita O(n^2) por particao mensal

`core/ingest/nwp._write_partitioned`: quando a particao `<ano>/<mes>.parquet` ja
existe, le o parquet inteiro, concatena, faz `unique`, ordena e reescreve. No bulk
isso ocorre uma vez por run (14 linhas), e a particao do mes cresce a cada run.
Para um mes com ~30 runs, o 30o run le/reescreve um arquivo ja com ~390 linhas;
custo acumulado e quadratico no numero de runs por mes.

Correcao recomendada: no caminho bulk, acumular as linhas do ano em memoria e
escrever cada particao mensal UMA vez ao final (ou agrupar por mes e dar um unico
flush por mes). As linhas sao pequenas (apenas TMP:2m), cabem em memoria sem
problema.

### PERF-4 (MEDIO) - `read_snapshots` recarrega e concatena tudo a cada chamada

`core/ingest/nwp.read_snapshots` faz `rglob("*.parquet")` + `pl.concat` de todas as
particoes a cada invocacao. No cross-check (opn5a_hfapi_vs_single_runs) e chamado
poucas vezes, entao o impacto e menor; mas combinado com `_anchor_series`, que
itera labels linha-a-linha e chama `select_max_trajectory_anchor` filtrando o frame
inteiro por data, vira O(n_datas x altura_snapshot). Para 2 anos isso ja pesa.
Sugestao: pre-indexar os snapshots por data (group_by/partition) antes do laco.

### PERF-5 (BAIXO) - `sleep` fixo e provenance acumulada

`_bulk` dorme `sleep` (default 0.2s) por run (~73s/ano) - aceitavel como politesse,
mas redundante se PERF-2 introduzir limite de concorrencia + jitter. Alem disso,
`DecodeProvenance.grid_lats/lons/distances_km/byte_ranges` acumulam uma entrada por
mensagem durante TODO o bulk (~5.100 entradas/ano), mas `_write_provenance` so grava
o indice [0]. E desperdicio de memoria e induz a leitura errada (a provenance
representa so o primeiro run/lead, nao o conjunto).

---

## 2. Corretude / robustez

### P1 (RESOLVIDO nesta sessao) - unlink de tempfile falha no Windows

`gfs_grib_decode.decode_tmp_2m_at_point` gravava a mensagem em
`NamedTemporaryFile(delete=False)` e chamava `Path(tmp_path).unlink()` no finally.
No Windows isso estoura WinError 32 (a lib C do eccodes ainda segura o handle no
momento do unlink), abortando o probe antes de avaliar os criterios do gate.
Corrigido para decodificar direto da memoria com
`eccodes.codes_new_from_message(message_bytes)` (imports `tempfile`/`Path`
removidos). Recomendacao: manter como esta - decode em memoria e mais rapido e
portavel; eh a abordagem correta.

### C1 (MEDIO) - Sem retry na camada HTTP do decoder; falha de 1 lead derruba o dia

`gfs_grib_decode._http_get_bytes/_text` nao tem retry/backoff (diferente de
`nwp_client._http_get`, que tem). No bulk, qualquer excecao em UM lead cai no
`except` de `_decode_run`/`_bulk`, que pula o RUN INTEIRO (perde os 14 leads do
dia) e segue. Em ~10k requisicoes/ano, falhas transitorias do S3 sao esperadas, e
o resultado e perda de dias inteiros de forma silenciosa (so contabilizada em
`n_ok`). Recomendacao: retry com backoff no GET (como ja existe no nwp_client) e,
idealmente, granularidade de falha por lead em vez de por run.

### C2 (BAIXO) - Filtro defensivo inalcancavel em `select_nwp_v1`

`core/ingest/nwp.select_nwp_v1`: apos `causal = snapshots.filter(run_time_utc <=
cutoff)`, o bloco `bad = causal.filter(run_time_utc > cutoff)` e sempre vazio por
construcao, logo o `RuntimeError` nunca dispara. E codigo morto disfarcado de
guardrail. Nao e bug, mas da falsa sensacao de protecao; ou remover, ou mover a
verificacao para ANTES do filtro (validando os snapshots crus).

### C3 (BAIXO) - Inconsistencia de faixa esperada no probe

O runbook diz "K->C ~6-14 C", o docstring de `gfs_grib_decode` diz "6-17C" e o
print do probe diz "expect ~6-17C". O gate real usa [-10,40] C, entao nao afeta a
decisao, mas as faixas-guia divergem entre doc e codigo. Alinhar para evitar ruido
em revisoes futuras.

### C4 (INFORMATIVO) - Particao por mes do run, nao do alvo

No bulk, o run das 18Z de d-1 cai na particao do mes de `run_time_utc`. Logo o alvo
2023-06-01 (run 2023-05-31 18Z) grava em `2023/05.parquet`. Comportamento correto e
coerente com o schema (particionado por valid_time/run), mas e contra-intuitivo na
inspecao manual - vale uma nota na provenance ou no runbook.

---

## 3. Arquitetura / seguranca (pontos fortes)

- Separacao eccodes-free bem feita: `core/ingest/grib_idx.py` e puro (somente
  construcao de chave S3, parse do `.idx`, byte-range) e testado em CI, enquanto
  eccodes fica restrito a `scripts/gfs_grib_decode.py` (import local), preservando o
  guardrail de determinismo REQ-MOD-6 (eccodes nunca no grafo de import do runtime).
- O gate por probe (validar gridpoint + K->C ANTES de decodificar 3 anos) e a
  ordem estrita (nada de recomputo de sha256 antes do probe) sao bem aplicados e
  pegaram o bug P1 exatamente como projetado.
- Byte-range via `.idx` (poucos KB por mensagem em vez de ~500 MB do campo cheio) e
  a decisao certa de eficiencia de transferencia.
- Rede so nos endpoints autorizados (S3 anonimo HTTPS, single-runs open-meteo);
  nenhum secret em codigo; idempotencia por dedup (model, endpoint, run_time_utc,
  valid_time_utc) com `keep="last"`.
- `nwp_client.load_nwp_model_specs` faz contrato runtime YAML<->codigo, falhando
  alto em divergencia - boa defesa contra config podre.

---

## 4. Prioridade sugerida

1. PERF-1 + PERF-2 (cliente reutilizado + concorrencia) - resolve a lentidao que
   motivou o pivo; maior ganho por esforco.
2. PERF-3 (flush por mes em vez de por run) - elimina a amplificacao quadratica.
3. C1 (retry no GET + falha por lead) - completude e robustez do bulk de 3 anos.
4. PERF-4, PERF-5, C2, C3, C4 - limpeza e ganhos menores.

Nada acima exige afrouxar threshold, mexer no gridpoint, na regra K->C, no sha256
de pre-registracao ou no evaluator. Sao mudancas de I/O e robustez, ortogonais ao
gate ja validado.
