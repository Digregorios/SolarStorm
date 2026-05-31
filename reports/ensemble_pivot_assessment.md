# Parecer: pivo para `ensemble_meteorological_forecaster_v1`

Julgamento sistematico do plano do `update.txt` (2026-05-31), aterrado no codigo atual, no
projeto da `quarentena` (ideias, codigo contaminado) e nos projetos de `projetos_github`
(analise de arquitetura). Documento de decisao - NENHUM codigo foi alterado.

---

## 1. Veredito de uma linha

**Acato a direcao (ensemble probabilistico em camadas), rejeito o sequenciamento e o escopo de
uma vez.** O plano esta meteorologicamente correto e alinhado ao que ja descobrimos
empiricamente (o bias audit mostrou que o problema e centro sob late-warming, nao IC). Mas como
esta escrito, ele e grande demais para um unico pivo e arrisca repetir o erro da quarentena
(muitas ideias boas, reconstrucao que nao fecha). A forma adequada e **incremental, cada arm
entrando como experimento pre-registrado que so sobrevive se passar walk-forward** - exatamente
o principio (3) do proprio plano, que o sequenciamento proposto viola ao listar 10 fases.

---

## 2. O que esta CERTO no plano (acato sem ressalva)

- **Ensemble em camadas, nao "modelo magico".** Correto e e o consenso da literatura + dos 3
  projetos github. O PolyWeather faz exatamente isso: multi-modelo Open-Meteo -> de-dup por
  familia (ICON-D2>ICON-EU>ICON; HRDPS>RDPS>GDPS>GEM) -> peso por 1/MAE -> recent signed-bias
  correction com shrinkage. O backtest deles (`deb_v1_raw` MAE 1.63 -> `recent_bias_corrected`
  MAE 1.50, bucket-hit 25.8%->31.4%) e evidencia de que bias-correction + blend ajuda.
- **Os 5 principios inegociaveis** (tudo por CP, walk-forward, EDA gera hipoteses nao modelos,
  separar forecast de trading, nunca tunar nos 4 dias frescos). Ja sao a disciplina do projeto;
  mante-los e obrigatorio. O ponto sobre split-conformal/climo-por-split ja foi forcado nas
  ultimas correcoes.
- **Ridge continua como arm, nao cerebro.** Correto e validado: o bias audit mostrou Ridge com
  menor MAE em dias de late-spike (0.61) - ele tem sinal de centro, so erra no regime de
  warming pos-CP. Descartar seria jogar fora sinal.
- **EDA por mes E regime, nao distribuicao total.** Concordo plenamente. A `TmaxHourClimatology`
  atual e marginal por mes; o GMM de regime nunca existiu (`nzwn/regimes/` vazio). A queixa do
  plano e legitima.
- **Camada de mercado separada e por ultimo.** Ja e a arquitetura (decision/sizing live-only).

## 3. O que precisa ser ESCLARECIDO ou ALTERADO (ressalvas)

1. **Sequenciamento: 10 fases simultaneas e o anti-padrao que matou a quarentena.** A quarentena
   tem a MESMA estrutura de pastas e specs deste projeto (Phases 0-2 + contratos), e foi
   abandonada. A licao e: nao abrir 6 contratos novos + 5 arms + ensemble + conformal de uma vez.
   **Alteracao:** ordenar por VALOR/RISCO e entregar UM arm por vez com gate. Ordem recomendada
   abaixo (secao 4).
2. **"NWP ensemble" ja foi parcialmente tentado e e caro.** O projeto ja tem `core/ingest/nwp*`,
   GFS s3_grib decodificado, e o Track Phase 4 inteiro. O plano fala em "Open-Meteo ensemble (31
   membros)" como se fosse novo - mas Open-Meteo multi-model (o que o PolyWeather usa, sem GRIB)
   e MAIS BARATO e mais simples que o caminho GFS-GRIB que ja sofremos. **Esclarecer:** o arm NWP
   v2 deve usar Open-Meteo multi-model API (deterministico, varios modelos), nao re-decodificar
   GRIB. Isso reaproveita a infra de causalidade (`run_time_utc <= cp - safety_margin`) sem o
   custo eccodes.
3. **Analogos: a ideia mais valiosa e a de maior risco de leakage.** k-NN sobre trajetorias e
   exatamente onde a causalidade quebra silenciosamente (distancia usando features pos-CP, ou
   vizinhos do futuro no walk-forward). **Alteracao:** o contrato de analogos DEVE proibir
   vizinhos com `date >= forecast_date` (nao so `ts < cp`), e o pool de analogos e so o train do
   split. Sem isso, vira nowcaster.
4. **"Regime path A->B->C" e atraente mas nao-testado e caro de rotular.** O plano propoe
   estados + trajetorias intradiarias + scores (foehn/clearing/southerly). Risco de inventar
   labels (o mesmo motivo do GMM ter sido adiado). **Esclarecer:** regimes entram primeiro como
   EDA/heuristica read-only (cortes no audit), e so viram feature se o `late_warming_precursor
   audit` mostrar lift real. Nao modelar regime antes de medir que ele separa o erro.
5. **Metadata explosion.** O plano lista ~10 campos `*_version` por forecast. Bom para auditoria,
   mas cada versao precisa de um contrato com teeth (hash) ou vira decoracao. **Alteracao:**
   adicionar campos de versao SOMENTE quando o componente correspondente existir e tiver
   contrato hasheado (como ja fazemos em prereg). Nao criar 6 contratos vazios na Fase 0.
6. **IC assimetrico por regime (cauda alta para late-warming).** Tentador, mas e exatamente o
   tipo de "abrir intervalo para cobrir" que o review anterior alertou. **Esclarecer:** so depois
   que o `ridge_conformal_minimal` por-regime mostrar que a assimetria melhora coverage SEM
   inflar largura nos dias calmos.

## 4. MELHORIAS / ordem adequada (o que eu faria)

A transicao certa nao e "Fase 0: 6 contratos". E uma fila de experimentos, cada um read-only ou
gated, reaproveitando o que ja existe:

1. **EDA profunda primeiro (read-only, zero risco), reaproveitando o bias audit.** Estender
   `late_warming_bias_audit` (ja existe e ja faz cortes por mes/late_spike/magnitude) com:
   decada-do-mes, hora-do-Tmax por mes, e "manha como preditor" (T_06, delta_min->cp). Saida:
   `reports/eda/*`. Isto responde "o sinal existe?" antes de qualquer modelo. **Maior valor,
   risco nulo.**
2. **Conformal por regime/late-warming-bucket** sobre o p50 ATUAL (Ridge ou empirical). Ja temos
   `ridge_conformal_minimal` com fallback hierarquico; adicionar um nivel de bucket
   (late_warming_risk) ANTES de cp_specific. Ataca o P0 (centro frio em warming) pela via de
   incerteza condicional, sem novo modelo de centro.
3. **Arm NWP via Open-Meteo multi-model** (nao GRIB): `P_nwp(k)` a partir do max-de-trajetoria
   dos membros, com bias-table por (mes, lead) - copiando a receita DEB do PolyWeather que
   comprovadamente reduz MAE. Gate: melhora RPS vs climatologia em >=2/3 splits.
4. **Arm analogos** (com o guardrail anti-leakage da ressalva 3). Gate: `analog_quality` alta
   melhora bracket-match; baixa -> cai para climo+NWP.
5. **Ensemble fixo pre-registrado** (pesos fixos, depois condicionais) so quando >=2 arms novos
   passarem isolados. Aceite: RPS melhora vs melhor arm individual, IC80 coverage ~0.80, NAO
   degrada dias calmos.
6. **Late-warming-aware center adjustment** (a conclusao do bias audit): modular so a cauda
   superior quando `material_late_warming_prob` alto, reusando o spike LGBM da Fase 7 que ja tem
   PR-AUC ~0.95. Esta e a correcao de centro que o audit apontou - e ela ja tem um modelo pronto.

## 5. Sobre as pastas que voce mandou analisar

- **quarentena/Wellington:** e uma copia anterior DESTE projeto (mesmas specs Phases 0-2, mesmo
  NZWN.csv, mesmo `core/`), nao um projeto diferente. Valor: confirma que a disciplina de
  contratos/causalidade ja estava certa; e serve de ALERTA - foi abandonada por excesso de
  reconstrucao. NAO ha codigo de regime/analogo pronto la para reaproveitar (as ideias estao nos
  specs, nao implementadas). Tratar como o plano pede: fonte de ideias, nao de codigo.
- **projetos_github:** os 3 sao bots de TRADING (Polymarket/Kalshi), nao forecasters de pesquisa.
  O unico com motor de Tmax serio e o **PolyWeather** (`src/analysis/deb_*`). Licoes de
  ENGENHARIA aproveitaveis (nao copiar codigo):
  - **DEB**: blend multi-modelo com de-dup por familia + peso 1/MAE + recent-bias com shrinkage.
    Receita simples e backtestada - bom molde para o nosso arm NWP/ensemble.
  - **HourlyPeakCorrector**: correcao de vies por HORA e por FASE (before/peak/after) do dia,
    com `min_samples` e clamp. E precisamente o esqueleto de uma correcao de centro
    late-warming-aware, com shrinkage por amostra - alinha com a ressalva 6.
  - **TAF como camada de supressao** (suppression_level/disruption_level), nao modelo primario.
    Confirma a posicao do design: TAF e alerta de risco de pico, nao gerador de Tmax. Util para
    o NZWN onde frentes/southerly cortam o pico.
  - O resto (pagamentos, supabase, frontend, telegram) e irrelevante para forecasting.

## 6. Riscos que o plano subestima

- **Custo de manutencao de 6 contratos + 10 versoes** num projeto de 1 pessoa/agente. Cada
  contrato hasheado e divida de manutencao. Comecar com 1-2.
- **Open-Meteo rate/quota** se o arm NWP multi-model for chamado por dia x cidade x CP.
- **Analogos sem dado suficiente**: 6 anos (2020-2026) de NZWN dao poucos analogos de alta
  aderencia para regimes raros; `analog_quality=low` sera comum -> precisa do fallback robusto.
- **Overfit de regime**: inventar 5 scores (foehn/clearing/southerly/marine/post-frontal) sem
  validacao e o caminho mais rapido de volta para a quarentena.

## 7. Recomendacao final

Aprovar a VISAO (ensemble em camadas, EDA-por-regime, Ridge como arm). NAO aprovar o pivo como
um big-bang de 10 fases. Executar como fila incremental (secao 4), comecando por **EDA profunda
read-only** (item 1) - que e o que o proprio plano lista como Etapa 1 e o que tem maior valor com
risco nulo - e so promover cada arm que sobreviver ao walk-forward. Reusar as RECEITAS do
PolyWeather (DEB blend, hourly/phase corrector, TAF-como-supressao) como molde de engenharia, nao
como codigo. Manter o nome interno honesto: isto e uma EVOLUCAO incremental do forecaster atual,
nao um `v1` do zero (o "do zero" foi a quarentena, e ela falhou).

---

## 8. Conciliacao apos rebate do revisor (2026-05-31) - ACORDADO

O revisor rebateu 4 atalhos do meu parecer. **Acato os 4 - estavam corretos.**

1. **Conformal por late_warming_bucket REAL e leakage. (acato; eu errei.)** `k_eod - k_cp` e
   ex-post; calibrar por ele usa o futuro. A ordem correta e: precursor audit -> risk score
   CAUSAL (features ate CP) -> conformal por PREDICTED risk bucket. E IC mais largo nao conserta
   o p50/probabilidade de bracket (o que importa para mercado) - so cobre. Meu item 2 cai.
2. **Multi-model deterministico != ensemble probabilistico. (acato a distincao.)** Multi-model
   (ECMWF/GFS/ICON) e diversidade entre modelos; ensemble perturbado e incerteza de condicoes
   iniciais. Usar multi-model como NWP **v0** (barato); manter ensemble-por-membros como v1
   futuro. Nao apagar a visao probabilistica.
3. **Spike LGBM ~0.95 NAO esta pronto. (acato - este e o rebate mais importante.)** Eu fui
   incoerente: declarei a quarentena contaminada e no mesmo parecer tratei o spike LGBM como
   pronto. PR-AUC 0.95 para spike meteorologico exige auditoria anti-leakage (coluna pos-CP, uso
   indireto de k_eod, split, dataset) ANTES de qualquer uso. E hipotese/arquitetura, nao
   componente confiavel.
4. **Regime path: auditar cedo, nao adiar. (acato o ajuste.)** Nao MODELAR cedo, mas o corte
   diagnostico de regime path entra na primeira leva read-only.

**Refino aceito (limite causal):** trocar "o sinal nao existe no CP" por "o sinal TERMICO
REALIZADO nao existe no CP, mas PRECURSORES meteorologicos podem existir". Essa nuance e o que
justifica o ensemble - e o trabalho da EDA e justamente provar/refutar que esses precursores
existem.

**Fila de execucao ACORDADA (substitui a secao 4):**
```
1. EDA profunda read-only (mes/decada, manha-como-preditor, delta-desde-minima,
   hora-do-Tmax por mes, E regime_path_eda) - estende late_warming_bias_audit
2. late_warming_precursor_audit -> mede lift de precursores CAUSAIS (gate: lift >=2/3 splits)
3. analog_retrieval_audit (read-only; guardrail: neighbor_date < forecast_date, pool=train)
4. NWP v0 via Open-Meteo multi-model (causal; bias-table por mes/lead/modelo)
5. late_warming_risk_model v0 (so se Etapa 2 mostrar sinal; causal, calibrado)
6. conditional conformal por PREDICTED risk bucket (+ teste de assimetria de cauda)
7. promover arms aprovados (P_ridge/P_empirical/P_climo/P_analog/P_nwp/P_late_warming)
8. ensemble fixo pre-registrado (so com >=2 arms novos aprovados)
9. ensemble condicional
10. market layer / shadow trading
```
Disciplina transversal acordada: cada experimento tem um prereg MINIMO
(`reports/experiments/<nome>_prereg.md` ou bloco no relatorio: target, features permitidas,
split, gate, metrica, fallback, criterio de falha) - sem contratos decorativos, mas sem garimpo.
Etapas 1-3 sao read-only (risco nulo). Nada promovido sem walk-forward. 4 dias frescos = sentinela,
nunca treino.
