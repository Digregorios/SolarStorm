# Code Review: polymarket-tmax-forecaster

Projeto muito bem arquitetado para um sistema em Fases 1/2. A abordagem de contratos imutaveis, enforcement de causalidade como erro fatal, e guards de CI (ASCII + reverse-import) sao excelentes. Abaixo os findings organizados por severidade.

---

## BUGS / CORRETUDE

### 1. `core/features/builder.py:157` — `__import__` inline

```python
cp_local = cp_utc.astimezone(__import__("zoneinfo").ZoneInfo(tz_name))
```

Uso de `__import__` inline e um code smell. Deveria ser `from zoneinfo import ZoneInfo` no topo do modulo.

### 2. `core/io/timeutil.py:62-81` — `cp_to_utc` logica fragil

O fallback com `for offset in (-1, 1, -2, 2)` e um cheiro de codigo. Se nenhum offset funcionar, a funcao retorna um `candidate` que pode estar **fora** da janela do dia local, sem levantar erro. Isso pode produzir previsoes para o dia errado silenciosamente.

### 3. `core/cli/ingest.py:75` — `build_features` nao passa `labels`

```python
feats = build_cp_features(obs, date_local=d, cp_hhmm=cp_hhmm, tz_name=cfg.tz)
```

O parametro `labels` nao e passado, entao features D-1 (`tmax_d_minus_1_int`, `tmin_d_minus_1_int`) serao sempre `None`.

### 4. `core/cli/forecast.py:69-80` — Calculo do IC80 impreciso

O sentinel `low == sorted_k[0]` para detectar se P10 ja foi setado e fragil. Se `sorted_k[0]` for de fato o P10 correto, a logica funciona por coincidencia, mas se o acumulado nunca atinge 0.10, `low` fica no primeiro elemento sem indicacao de que o IC e degenerado.

### 5. `audits/run_h0_audit.py:156` — Logica H0_rejected confusa

```python
h0_rejected = bool(gate_violations) is False and all(...)
```

Dupla negacao + `is False` em booleano e anti-pythonico. O correto seria:

```python
h0_rejected = not gate_violations and all(e.get("passed") is not False for e in evidence)
```

Alem disso, o nome da variavel e enganoso: `H0_rejected = True` significa que o modelo **passou** na auditoria (rejeitou a hipotese nula de nowcasting). Isso deveria ser documentado.

---

## PERFORMANCE

### 6. `core/features/builder.py:195-230` — `build_panel` e O(n^2)

Para cada data (~2000 dias), a funcao filtra `labels` 2-3 vezes com `labels.filter(pl.col("date_local") == d)`. Isso resulta em milhares de scans lineares. Para 5 anos de dados sao ~2000 dias x 4 CPs x 2 filtros = ~16.000 operacoes de filtro. Deveria usar um `dict` lookup ou join:

```python
label_map = {row["date_local"]: row for row in labels.to_dicts()}
```

### 7. `core/features/builder.py:209-220` — `except Exception` engole erros

```python
except Exception:
    base[f"k_cp__cp_{cp[:2]}"] = None
```

Isso mascara bugs reais. Se `build_cp_features` falhar por um motivo legitimo (ex: dados corrompidos), o erro e silenciosamente ignorado.

---

## FEATURES INCOMPLETAS / GAPS

### 8. `nzwn/config/features.yaml` nunca e consultado

O arquivo declara 18 features baseline como toggles, mas `build_cp_features()` nunca le esse YAML. Features marcadas como `false` continuam sendo computadas (ou, na pratica, nem existem — ver proximo ponto).

### 9. 7 das 18 features declaradas nao sao computadas

O `features.yaml` lista: `last_obs_dwp_c_int`, `time_since_new_max_min`, `wind_dir_sincos`, `dp_qnh_3h`, `vis_km`, `ceiling_m`, `wx_flags`. Nenhuma dessas e implementada em `build_cp_features()`. O `clim_tmax_c_dec` e `clim_tmax_int` sao setados como `None` (placeholder para o caller preencher), mas ninguem preenche.

### 10. `core/io/logging.py:24-27` — `current_run_id()` auto-cria silenciosamente

Se `log_event` for chamado antes de `new_run_id()`, um UUID e gerado automaticamente. Isso esconde bugs de inicializacao — o comportamento esperado seria levantar erro.

---

## QUALIDADE DE CODIGO

### 11. `core/ingest/iem_csv.py:94-102` — Deteccao de implausibilidade re-executa regex

```python
if q == "missing" and raw_metar and _METAR_TT_DD.search(str(raw_metar)):
    n_impl += 1
```

A regex e executada duas vezes para linhas implausiveis. `parse_tmp_c_int_from_row` deveria retornar um flag `implausible` diretamente.

### 12. `core/baselines/empirical.py:30` — Default enganoso

```python
train_window: tuple[date, date] = (date(1970, 1, 1), date(1970, 1, 1))
```

Unix epoch como default e misleading se alguem inspecionar o objeto. Melhor usar `None` ou levantar erro se nao fornecido.

### 13. Dependencia `pandas` desnecessaria

`pandas>=2.1` esta em `dependencies` mas nunca e importado no codigo. Polars e usado exclusivamente. Remover reduz o footprint de instalacao.

### 14. `core/ingest/snapshot.py:52-61` — Manifest reescrito integralmente

Cada chamada reescreve o manifest inteiro do zero. Para uso incremental (ex: adicionar um dia), isso e ineficiente e pode perder entries se o CSV fonte mudar entre execucoes.

### 15. `core/features/builder.py:133-148` — Slope usa `tmpf` (Fahrenheit)

`_compute_slope` converte `tmpf` para Celsius internamente, mas `tmpf` e explicitamente documentado como "segunda classe" (design 4.1.2). Deveria usar `tmp_c_int` que e o sinal de verdade, ou pelo menos documentar a razao.

---

## POSITIVO

- **Arquitetura de causalidade**: o enforcement via `RuntimeError` + verificacao independente no audit e excelente
- **Contratos imutaveis como codigo**: Pydantic + YAML + versionamento (Q_VERSION) e uma abordagem madura
- **CI guards**: ASCII guard + reverse-import guard como testes de integracao e uma pratica incomum e valiosa
- **Subprocess isolation** para o audit: evita que `core/` tenha dependencia estatica de `audits/`
- **Snapshot deterministico** com SHA256: reprodutibilidade real, nao apenas teorica
- **Testes golden** com fixtures frozen: detecta regressoes silenciosas
- **Smoothing circular** na climatologia: tratamento correto de wrap DOY
- **DST handling**: testes cobrem 10 datas incluindo transicoes de 23h/25h

---

## RESUMO

| Categoria | Contagem |
|-----------|----------|
| Bugs/corretude | 5 |
| Performance | 2 |
| Features incompletas | 3 |
| Qualidade de codigo | 5 |
| **Total findings** | **15** |

### Top 3 prioridades

1. **`build_panel` O(n^2)** — vai travar em producao com dados reais
2. **`cp_to_utc` retorno silencioso fora da janela** — pode produzir previsoes para o dia errado
3. **Features do YAML nao enforcement** — da falsa sensacao de controle sobre o que e computado
