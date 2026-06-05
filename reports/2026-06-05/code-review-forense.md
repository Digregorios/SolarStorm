⚠️ **SUPERSEDED** — produzido com bugs de causalidade (ver `code-review-forense.md`). Não usar para decisão.

# Code review forense — SolarStorm

**Data:** 2026-06-05  
**Projeto:** `Wellington/SolarStorm`  
**Foco:** lógica, causalidade, métricas, bugs silenciosos e inconsistências entre implementação, testes e documentação.

## Validação executada

```bash
uv run python -m pytest -q -m "not network"
```

Resultado:

```text
106 passed, 2 deselected
```

Ou seja: os problemas abaixo são majoritariamente **silenciosos** — passam na suíte offline.

Também foram executados probes mínimos para confirmar alguns achados críticos:

- L4 empírico com CP sem dois-pontos funciona como `conditional`; com CP do CLI (`"23:00"`) cai em `uniform`.
- `round(20.5)` retorna `20`, enquanto settlement half-up retorna `21`.
- `day_local_window()` em transição de DST retorna datetimes locais cujo delta direto dá `24h`, mas em UTC real dá `23h`.
- `regime_label` pode ser preenchido com dados pós-CP mesmo quando não há nenhuma observação causal antes do CP.
- `day_complete=True` para 40 observações concentradas nos primeiros 40 minutos do dia.

---

# Resumo executivo

O projeto tem uma boa intenção arquitetural — causal firewall, gates congelados, walk-forward, artefatos auditáveis — mas a implementação atual tem violações silenciosas justamente nos pontos que deveriam proteger o sistema:

1. **Causalidade está quebrada em features centrais.**  
   O firewall só verifica `slice_df`, mas várias features usam regime full-day, labels do próprio dia e estatísticas calculadas com todo o dataset.

2. **A validação não compara contra o melhor null por CP.**  
   O G5 existe no papel, mas na prática passa sempre.

3. **O baseline L4 empírico está quebrado no CLI.**  
   Ele é treinado com CP `"2300"`, mas predito com `"23:00"`, caindo em fallback uniforme.

4. **A métrica de settlement/risk está invertida ou inconsistida.**  
   O projeto usa `round()` bancário em lugares que deveriam usar half-up, e `flip_risk` chama “risco máximo” o ponto mais seguro do bucket.

5. **Labels podem ser marcados como completos sem cobertura diária real.**  
   Isso pode contaminar `tmax_int`, `tmax_hour`, treino, validação e leaderboard.

---

# Achados críticos

## 1. Vazamento de futuro no `regime_label` e derivados

**Severidade:** crítica  
**Arquivos:**

- `solarstorm/features/builder.py:189-193`
- `solarstorm/features/builder.py:279-294`
- `solarstorm/features/builder.py:506-510`
- `solarstorm/eda/_regimes.py:52-67`

O builder calcula o regime uma vez por dia usando `day_obs` completo:

```python
day_obs = obs.filter(pl.col("date_local") == d)
date_regimes[d] = _classify_regime_for_date(day_obs)
```

Depois esse `regime_label` é reutilizado em todos os CPs do dia, inclusive quando `slice_df.height == 0`, ou seja, quando não existe nenhuma observação causal antes do checkpoint.

O firewall causal só verifica:

```python
feature_max_ts = slice_df["valid"].max()
require_causal(feature_max_ts=feature_max_ts, cp_utc=cp_utc_val)
```

Ele não sabe que `regime_label` veio de observações pós-CP.

Um probe confirmou que chuva apenas pós-CP gera `regime_label='disrupted'` para CP `20:00`, enquanto as features do slice causal saem `None`.

**Impacto:**  
Qualquer hipótese ou segmento usando regime pode carregar informação do futuro. Isso invalida a validação de features dependentes de regime e pode inflar resultados sem quebrar testes.

**Correção sugerida:**

- Calcular regime por `(date_local, cp)` usando apenas `slice_df`.
- Se não houver observação pré-CP, `regime_label` deve ser `None`/`unknown`.
- Incluir dependências de regime no `feature_max_ts` ou criar um manifesto de proveniência por feature.
- Adicionar teste onde observações pós-CP alteram regime, mas a feature pré-CP não pode mudar.

---

## 2. Features usam o alvo do próprio dia e estatísticas do dataset inteiro

**Severidade:** crítica  
**Arquivos:**

- `solarstorm/features/builder.py:201-229`
- `solarstorm/features/builder.py:244-267`
- `solarstorm/features/builder.py:366-370`
- `solarstorm/features/builder.py:416-423`

Exemplos:

### `day_sequence_pattern`

```python
tmax_d = lr.get("tmax_int")
...
elif tmax_dminus2 < tmax_dminus1 < tmax_d:
    day_seq = "warming"
```

Usa `tmax_d`, que é o próprio target final do dia.

### `tmin_delta_tmax`

```python
tmin_delta_tmax = tmin_d - tmax_dminus1
```

`tmin_d` é o mínimo do dia inteiro; pode ocorrer depois do checkpoint.

### `hours_to_expected_peak` / `tmax_hour_by_regime_month`

```python
mr_stats = labels_w_regime.group_by(["_month", "_regime"]).agg(
    pl.col("tmax_hour").mean()
)
```

Calculado sobre todos os labels fornecidos, não dentro da janela de treino do split.

### `late_warming_anomaly`

```python
regime_kcp = labels_w_regime.group_by("_regime").agg(...)
...
late_warming_anomaly = (k_cp - stats["mean"]) / max(stats["std"], 1.0)
```

Também usa estatística global, incluindo datas futuras em validação walk-forward.

**Impacto:**  
A validação pode estar testando features com informação que não existiria no momento do forecast. Isso é o pior tipo de bug silencioso: melhora métricas, passa testes e parece “evidência”.

**Correção sugerida:**

- Remover `tmax_d` de features pré-CP. Para sequência, usar `D-1`, `D-2`, `D-3`.
- Trocar `tmin_d` por `tmin_so_far_at_cp` se a intenção for causal.
- Recalcular climatologias e normalizações dentro de cada split de treino.
- Não persistir features que dependem de estatísticas future-aware em `features.parquet` sem versionar a janela de treino.

---

## 3. G5 “best-null per CP” é inoperante

**Severidade:** crítica  
**Arquivos:**

- `solarstorm/eda/_validate.py:371-389`
- `solarstorm/eda/_validate.py:245-253`
- `docs/decisions/003-frozen-gates.md:23-30`
- `docs/decisions/005-multi-cp-design.md:14-22`

A documentação exige comparação contra o **melhor null por CP**. Mas a validação calcula apenas L0 persistence:

```python
cp_err[d] = float(abs(kcp_int - tmax_int))
```

Depois passa:

```python
best_null_mae=baseline_mae,
per_cp_passed=True,
```

Ou seja, G5 sempre passa. G1 também compara o modelo contra L0, não contra o melhor null real.

**Impacto:**  
Uma hipótese pode ser marcada como `validated` por vencer persistence, mesmo perdendo para climatologia, dminus1 ou L4 no mesmo CP.

**Correção sugerida:**

- Dentro do walk-forward, calcular L0/L1/L2/L4 por split e CP.
- Passar `best_null_mae_by_cp` real para G1/G5.
- Trocar `per_cp_passed=True` por comparação efetiva.
- Adicionar teste sintético: feature vence L0, perde para L2, deve ser rejeitada.

---

## 4. L4 empírico cai em fallback uniforme no CLI

**Severidade:** crítica  
**Arquivos:**

- `solarstorm/baselines/_empirical.py:73-80`
- `solarstorm/__main__.py:327-329`

No fit:

```python
cp = col.replace("k_cp__cp_", "")
```

A chave fica `"2300"`.

No CLI:

```python
dist, source = emp.predict_dist(
    month=d.month, cp=str(cp_str), k_cp=kcp_int,
)
```

`cp_str` é `"23:00"`.

Resultado confirmado por probe:

```text
conditional
uniform
```

Com `"2300"` encontra o bucket. Com `"23:00"` cai em `uniform`.

**Impacto:**  
O L4 no leaderboard não está avaliando o baseline empírico real. Métricas, fallback rate e comparação de best-null ficam distorcidas.

**Correção sugerida:**

- Criar normalizador único de CP: `"23:00" -> "2300"` ou vice-versa.
- Usar esse normalizador no fit, predict e CLI.
- Adicionar teste de integração com CP no formato `"23:00"`.

---

## 5. `flip_risk`/`risco_de_flip` estão conceitualmente invertidos

**Severidade:** alta/crítica para sizing de mercado  
**Arquivos:**

- `solarstorm/data/_settlement.py:30-50`
- `solarstorm/data/_labels.py:20-26`
- `tests/test_settlement.py:19-28`
- `tests/test_labels.py:48-55`
- `docs/decisions/002-integer-settlement.md:22-24`

O código e os testes dizem:

```python
flip_risk(15.0).risk == 0.5   # "max risk"
flip_risk(15.5).risk == 0.0   # "zero risk"
```

Mas isso é o oposto da sensibilidade ao boundary.

- Em `15.0`, o forecast está no centro do bucket. Um erro de `0.1°C` não muda o bracket.
- Em `15.5`, está exatamente na fronteira. Qualquer microvariação para baixo muda o bucket.

O valor calculado hoje parece ser “distância até a boundary”, não “risco de flip”. A nomenclatura e a documentação estão invertendo o significado operacional.

**Impacto:**  
Qualquer lógica futura de position sizing ou alerta de boundary risk usará confiança máxima onde deveria ter cautela mínima — e cautela mínima no ponto mais perigoso.

**Correção sugerida:**

- Renomear métrica atual para algo como `boundary_distance`.
- Se quiser `flip_risk`, definir alto perto de `.5` e baixo perto do centro do bucket.
- Ajustar docs e testes.
- Exemplo esperado para risco:

```python
risk = 0.5 - distance_to_nearest_half_boundary
# ou normalizado 0..1
risk = 1.0 - min(distance / 0.5, 1.0)
```

---

# Achados altos

## 6. `day_complete` aceita cobertura concentrada e ignora `min_quartile_coverage`

**Severidade:** alta  
**Arquivos:**

- `solarstorm/data/_labels.py:13-17`
- `solarstorm/data/_labels.py:76-82`

`DayCompleteParams` define:

```python
min_quartile_coverage: int = 1
```

Mas esse parâmetro nunca é usado. O dia é considerado completo apenas por:

```python
n_obs >= min_obs
max_gap_min <= max_gap_minutes
```

Isso ignora:

- gap do início do dia até a primeira observação;
- gap da última observação até o fim do dia;
- distribuição por blocos/quartis.

Probe confirmou que 40 observações nos primeiros 40 minutos do dia produzem:

```text
day_complete=True
```

**Impacto:**  
`tmax_int` pode ser subestimado e marcado como completo. Isso contamina labels, treino, validação e leaderboard.

**Correção sugerida:**

- Calcular janela local completa do dia.
- Incluir gaps de borda: início→primeira obs e última obs→fim.
- Exigir cobertura mínima por quartil/bloco.
- Adicionar teste com observações concentradas no começo do dia.

---

## 7. Métricas de bracket usam `round()` bancário contra contrato half-up

**Severidade:** alta  
**Arquivos:**

- `solarstorm/data/_settlement.py:13-20`
- `solarstorm/eval/_metrics.py:43-44`
- `solarstorm/baselines/_ladder.py:41`
- `solarstorm/__main__.py:317`
- `solarstorm/__main__.py:444`

Contrato:

```python
integer_settlement(dec) = floor(dec + 0.5)
```

Mas vários lugares usam `round()`:

```python
round(p50)
round(climo.tmax_dec_for(d))
round(kcp_val + pred_rw)
```

Probe:

```text
round(20.5) -> 20
integer_settlement(20.5) -> 21
bracket_match_at_p50(20.5, 21) -> 0.0
```

**Impacto:**  
Previsões em `.5` são avaliadas no bucket errado. Isso afeta bracket match e métricas de modelos que produzem valores decimais.

**Correção sugerida:**

- Trocar todos os `round()` de settlement/bracket por `integer_settlement()` ou `bracket_for()`.
- Adicionar testes para `14.5`, `20.5`, negativos e `bracket_match_at_p50`.

---

## 8. `hours_to_expected_peak` mistura hora UTC com hora local

**Severidade:** alta  
**Arquivos:**

- `solarstorm/features/builder.py:270`
- `solarstorm/features/builder.py:353-357`

O código usa:

```python
cp_hour = int(cp_str.split(":")[0])
hours_to_peak = float(expected_peak) - cp_hour
```

Mas `cp_str` é UTC (`20`, `21`, `22`, `23`) e `expected_peak` vem de `tmax_hour`, que é local.

Exemplo: CP `20:00 UTC` em NZST é `08:00 local`. Se o pico esperado é `15:00 local`, o lead-time correto é `+7h`; o código calcula `15 - 20 = -5`.

**Impacto:**  
A feature H2 fica com sinal e magnitude errados, possivelmente parecendo “preditiva” por artefato.

**Correção sugerida:**

```python
cp_local_hour = cp_utc_val.astimezone(ZoneInfo(TZ_NAME)).hour
hours_to_peak = expected_peak - cp_local_hour
```

Adicionar testes NZST e NZDT.

---

## 9. G4 classifica morning/evening com data fixa e ignora DST real

**Severidade:** alta  
**Arquivos:**

- `solarstorm/eval/_gates.py:69-78`
- `docs/decisions/005-multi-cp-design.md:8`

O gate usa uma data fixa de inverno:

```python
dummy_utc = dt.datetime(2025, 6, 15, cp_hour, 0, tzinfo=dt.timezone.utc)
```

Mas em NZDT, `23:00 UTC` cai em `12:00 local`. Probe confirmou:

```text
CP23 em janeiro -> local hour 12
```

O código ainda trata como morning porque calcula usando junho.

**Impacto:**  
O caminho do G4 muda: CPs que deveriam cair na regra de nowcasting/evening podem receber regra relaxada de morning.

**Correção sugerida:**

- `apply_all_gates()` deve receber `date_local` ou `cp_utc` real.
- Classificar morning/evening com timezone da data avaliada.
- Testar CP23 em NZDT.

---

## 10. Validação por regime provavelmente nunca é gerada

**Severidade:** alta  
**Arquivos:**

- `solarstorm/eda/_validate.py:507-517`
- `solarstorm/eda/_validate.py:555-569`

A segmentação por regime procura resultados já `validated`:

```python
validated_ids_cps = {
    (r.id, r.cp) for r in all_results if r.status == "validated"
}
```

Mas `_compute_single_result()` retorna:

```python
status="pending"
```

O status só vira `validated` depois, em etapa posterior.

**Impacto:**  
Mesmo que uma hipótese passe em `"all"`, os resultados por regime tendem a nunca ser calculados.

**Correção sugerida:**

- Finalizar status/FDR dos resultados `"all"` antes da segmentação.
- Ou selecionar candidatos por predicado explícito: `passes and gates preliminares`.
- Adicionar teste exigindo resultados regime-specific quando há regimes com `n >= 30`.

---

## 11. OLS pode validar intercepto, não a feature

**Severidade:** alta  
**Arquivo:**

- `solarstorm/eda/_validate.py:57-98`

O challenger é:

```python
remaining_warming ~ intercept + feature
```

Comparado contra L0 persistence. Se `remaining_warming` tem viés médio positivo, o intercepto sozinho já melhora o modelo. A feature pode receber crédito por uma simples calibração incondicional.

**Impacto:**  
Uma feature sem sinal real pode parecer validada.

**Correção sugerida:**

- Comparar contra null calibrado por CP: `k_cp + mean_train_remaining_warming`.
- Ou exigir ganho incremental contra modelo intercept-only.
- Reportar slope, variância da feature e ganho incremental.

---

# Achados médios

## 12. Benjamini-Hochberg usa denominador errado

**Severidade:** média  
**Arquivo:**

- `solarstorm/eda/_validate.py:158-188`

A docstring diz que só resultados com `p_value != None` entram no FDR. Mas:

```python
m = len(results)
```

é calculado antes de filtrar os resultados sem p-value.

**Impacto:**  
Features bloqueadas, categóricas ou all-null tornam o FDR artificialmente mais conservador.

**Correção sugerida:**

```python
indexed = [...]
m = len(indexed)
```

---

## 13. Features categóricas cadastradas não são testáveis pelo harness atual

**Severidade:** média/alta  
**Arquivos:**

- `solarstorm/eda/_catalog.py:19-21`
- `solarstorm/eda/_catalog.py:43-45`
- `solarstorm/eda/_catalog.py:79-83`
- `solarstorm/eda/_validate.py:81-83`

O catálogo inclui `regime_label`, `day_sequence_pattern`, `regime_score_argmax`, mas `_fit_ols_challenger()` rejeita não-numéricos:

```python
if not np.issubdtype(feat_vals.dtype, np.number):
    return None
```

**Impacto:**  
Parte do catálogo é rejeitada por limitação do harness, não por evidência negativa.

**Correção sugerida:**

- One-hot/regularização para categóricas.
- Booleanos convertidos explicitamente para `0/1`.
- Ou status `BLOCKED_UNSUPPORTED_TYPE`, não `rejected`.

---

## 14. `tmax_hour` não garante primeira ocorrência real do Tmax

**Severidade:** média  
**Arquivo:**

- `solarstorm/data/_labels.py:56-68`

Comentário:

```python
# first occurrence
```

Implementação:

```python
pl.col("hour_local")
  .sort_by("tmp_c_int", descending=True)
  .first()
```

Não há desempate por timestamp.

**Impacto:**  
Em dias com múltiplas observações empatadas no Tmax, `tmax_hour` pode depender da ordem de entrada.

**Correção sugerida:**

- Ordenar por `tmp_c_int desc, ts_local asc`.
- Ou selecionar explicitamente a primeira linha onde `tmp_c_int == max`.

---

## 15. Labels de settlement aceitam temperatura `imputed`

**Severidade:** média  
**Arquivos:**

- `solarstorm/data/_metar.py:53-63`
- `solarstorm/data/_labels.py:53-58`

Quando não há TT/DD no METAR, o parser usa `tmpf`:

```python
tt = round((tmpf - 32.0) * 5.0 / 9.0)
return tt, None, "imputed", False
```

Depois labels filtram apenas:

```python
dq_tmp_c_int != "missing"
```

Logo `imputed` entra em `tmax_int`, `k_cp`, `day_complete`.

**Impacto:**  
O target de settlement pode ser definido por conversão de Fahrenheit, embora a documentação diga que o contrato liquida no inteiro reportado no METAR bruto.

**Correção sugerida:**

- Para target/settlement, usar apenas `dq_tmp_c_int == "ok"`.
- Ou manter colunas de qualidade explícitas: `tmax_source`, `k_cp_source`, `n_imputed`.
- Decidir via ADR se imputação pode ou não definir settlement.

---

## 16. `tmax_int` e `tmax_dec` podem vir de observações diferentes

**Severidade:** média  
**Arquivo:**

- `solarstorm/data/_labels.py:56-74`

`tmax_int` vem de:

```python
pl.col("tmp_c_int").max()
```

`tmax_dec` vem de:

```python
pl.col("tmpf").max()
```

Esses máximos podem ocorrer em linhas diferentes.

**Impacto:**  
`risco_de_flip` pode descrever a boundary de uma leitura decimal que não corresponde ao inteiro que liquidou o target.

**Correção sugerida:**

- Escolher linha canônica do Tmax.
- Carregar juntos: `tmax_int`, `tmax_dec`, `tmax_ts`, `source`.
- Se quiser manter ambos, nomear separadamente: `tmax_int_metar_max` e `tmax_dec_sensor_max`.

---

## 17. Dewpoint não é validado

**Severidade:** média  
**Arquivos:**

- `solarstorm/data/_metar.py:66-72`
- `solarstorm/data/_obs.py:31-33`

Temperatura tem plausibilidade, dewpoint não. Também não há checagem básica de `dewpoint <= temperature`.

**Impacto:**  
Dewpoint corrompido gera `dw_depression_c_int` impossível e contamina features como `dewpoint_depression`, `foehn_score`, `dewpoint_collapse_rate_3h`.

**Correção sugerida:**

- Validar range de dewpoint.
- Sinalizar `dwp > tt`.
- Centralizar bounds em `_config.py`.

---

## 18. Missing/unknown de céu e chuva vira “claro/seco”

**Severidade:** média  
**Arquivos:**

- `solarstorm/features/builder.py:33-34`
- `solarstorm/features/builder.py:109-120`
- `solarstorm/features/builder.py:123-144`
- `solarstorm/features/builder.py:147-151`

Exemplo:

```python
def _coverage_weight(code):
    return _SKY_WEIGHTS.get(code, 0.0)
```

Código desconhecido ou ausente vira peso `0.0`, igual a céu claro.

**Impacto:**  
Ausência de dado vira sinal meteorológico benigno.

**Correção sugerida:**

- Retornar `None` para unknown/missing.
- Só retornar `0.0` quando houver evidência explícita de `CLR`/sem precipitação.
- Adicionar flags de cobertura/qualidade por feature.

---

## 19. Métricas probabilísticas existem, mas quase não são usadas

**Severidade:** média  
**Arquivos:**

- `solarstorm/eval/_metrics.py:47-63`
- `solarstorm/baselines/_ladder.py:79-90`
- `solarstorm/__main__.py:333-338`

`rps()` existe, mas o CLI não calcula RPS para L4. Além disso:

```python
rps_vals = [r.rps for r in group if r.rps]
```

descarta `0.0`, que é um RPS perfeito legítimo.

`p50_mode_share` também fica default `0.0`, então G3 tende a passar sempre no leaderboard.

**Impacto:**  
O leaderboard parece probabilístico, mas reporta defaults/zeros enganosos.

**Correção sugerida:**

- Trocar `rps: float = 0.0` por `float | None`.
- Agregar com `is not None`.
- Calcular RPS para distribuições.
- Calcular `p50_mode_share` a partir das previsões reais.

---

## 20. L4 chama modo de `p50`

**Severidade:** média  
**Arquivo:**

- `solarstorm/__main__.py:326-332`

O código faz:

```python
l4_p50 = max(dist, key=dist.get)
```

Isso é o modo/MAP, não a mediana.

**Impacto:**  
MAE e bracket match do L4 avaliam o modo enquanto o nome sugere p50. Pode distorcer comparação com modelos que emitam quantis.

**Correção sugerida:**

- Calcular p50 pela CDF acumulada.
- Se o modo for útil, reportar separadamente como `mode`.

---

## 21. `support_k` do L4 usa dados do período de teste

**Severidade:** média  
**Arquivo:**

- `solarstorm/__main__.py:253-260`

O fit usa `train_labels`, mas o suporte vem de:

```python
support_k = sorted(complete["tmax_int"].unique().to_list())
```

`complete` inclui o período recente avaliado.

**Impacto:**  
Mesmo sem usar contagens futuras, a distribuição sabe quais valores de Tmax aparecem no futuro/teste.

**Correção sugerida:**

```python
support_k = sorted(train_labels["tmax_int"].unique().to_list())
```

---

## 22. Walk-forward anual usa 365 dias fixos

**Severidade:** média  
**Arquivo:**

- `solarstorm/eval/_walkforward.py:29`

```python
test_end = ts + timedelta(days=test_length_days - 1)
```

Com `test_length_days=365`, anos bissextos iniciados em Jan-1 terminam em Dec-30.

Holdouts também são adicionados sem validar `min_train_days`.

**Impacto:**  
Splits “anuais” podem omitir dias; holdouts podem ter treino insuficiente.

**Correção sugerida:**

- Para split anual, usar `date(y + 1, 1, 1) - 1 day`.
- Aplicar `min_train_days` também a holdouts.

---

# CI, testes e auditabilidade

## 23. CI usa ferramentas que não estão em `.[dev]`

**Severidade:** média  
**Arquivos:**

- `pyproject.toml:11-12`
- `.github/workflows/ci.yml:18-25`

`dev` inclui só:

```toml
dev = ["pytest>=8", "httpx>=0.27"]
```

Mas CI executa:

```yaml
ruff check .
mypy solarstorm
```

**Impacto:**  
Em runner limpo via `pip install -e ".[dev]"`, `ruff` e `mypy` podem não existir.

**Correção sugerida:**

- Adicionar `ruff` e `mypy` aos extras dev.
- Ou mudar CI para fluxo `uv` se o lock for a fonte de verdade.

---

## 24. CI roda testes de rede por padrão

**Severidade:** média  
**Arquivos:**

- `.github/workflows/ci.yml:27-28`
- `pyproject.toml:20-22`
- `tests/test_iem.py`

O marker `network` existe, mas CI roda:

```yaml
pytest -q
```

**Impacto:**  
CI depende de IEM externo, rede e latência.

**Correção sugerida:**

```yaml
pytest -q -m "not network"
```

Rodar testes de rede em job manual/agendado.

---

## 25. Artefatos de leaderboard sobrescrevem runs do mesmo dia

**Severidade:** baixa/média  
**Arquivos:**

- `solarstorm/eval/_leaderboard.py:48-54`
- `docs/principles.md:51-58`

P5 diz “never overwrites”, mas o arquivo é:

```python
YYYY-MM-DD-leaderboard.json
YYYY-MM-DD-leaderboard.md
```

Duas execuções no mesmo dia sobrescrevem o resultado anterior.

**Correção sugerida:**

- Incluir timestamp UTC ou run-id no filename.
- Opcionalmente manter `latest` como alias.

---

# Ordem recomendada de correção

1. **Congelar uso dos reports atuais para decisão real.**  
   Há risco de leakage e leaderboard distorcido.

2. **Corrigir causalidade das features.**  
   Especialmente `regime_label`, `day_sequence_pattern`, `tmin_delta_tmax`, H11/H15 e estatísticas train-only.

3. **Corrigir labels e settlement.**  
   `day_complete`, imputações, `flip_risk`, `round()` bancário.

4. **Reescrever validação contra best-null real por CP.**  
   Implementar L0/L1/L2/L4 dentro do walk-forward e conectar G1/G5.

5. **Consertar L4 empírico no CLI.**  
   Normalizar CP, usar suporte train-only, calcular p50 real e RPS.

6. **Adicionar testes de regressão específicos para os bugs silenciosos.**  
   Principalmente:
   - post-CP não altera feature pré-CP;
   - CP `"23:00"` funciona no L4;
   - `.5` usa half-up em métricas;
   - `day_complete` falha com cobertura concentrada;
   - FDR ignora resultados sem p-value;
   - CP23 em NZDT não é classificado como morning.

---

# Veredicto

O projeto tem boa estrutura e uma suíte razoável, mas os mecanismos de segurança mais importantes estão parcialmente “cenográficos”: existem nomes, docs e gates, porém algumas implementações não protegem contra os bugs que dizem prevenir.

A falha principal é **causalidade**. Se isso não for corrigido primeiro, qualquer melhoria estatística posterior pode ser apenas vazamento futuro bem disfarçado.
