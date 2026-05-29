# Polymarket Tmax Forecaster — Design & Specs (v1)

## 0) Objetivo

Construir um sistema **intraday** de previsão de **Tmax resolvido no METAR (inteiro em °C)** para mercados de previsão (ex.: Polymarket), com:

- Atualização por checkpoints (CPs) conforme novos dados chegam
- Métricas e auditoria anti-nowcaster
- **Confiança calibrada** (selecionar quando operar e quando ficar fora)
- Um módulo separado de **late spike** (proteção e edge em 1-cent)

## 1) Escopo (o que é / o que não é)

**É:** forecast do dia corrente (D0), com o dia já em andamento; múltiplas previsões ao longo do dia.  

**Não é:** previsão de longo prazo (D+3, D+10).  

**Foco inicial:** NZWN (Wellington). Arquitetura modular para replicar depois, sem adicionar multi-cidade agora.

## 2) Definição do alvo (contrato de quantização)

### 2.1 Verdade operacional

O sistema deve operar no mesmo espaço que o mercado/observação: **inteiros de Tmax em °C** (METAR).

### 2.2 Função de quantização (Q) — DEFINIDA (default)

Observacao: o dataset historico de METAR para NZWN fornece **temperatura em inteiro (°C)**. Ou seja, o "valor observado" ja chega quantizado.

Definir uma função oficial `Q(x)` que mapeia um Tmax contínuo (latente) para o inteiro METAR. O projeto usa a seguinte definicao default (simples e limpa) em:

- geração de labels
- treino (loss)
- avaliação
- relatórios/postmortem

Bandas inversas (default):

- `B(k) = [k-0.5, k+0.5)`

Quantizacao (default):

- `Q(x) = floor(x + 0.5)` (round-half-up)

Interpretacao no dataset:

- Observacoes METAR inteiras: `k_obs` e o inteiro publicado (identidade no espaco observado).
- O contrato acima e usado para mapear outputs continuos do modelo e para loss band-aware / distance-to-band.

Se houver evidencia de que o mercado/resolver usa outra regra (secao 2.4), a diferenca deve ser documentada explicitamente (com versao do contrato).

### 2.4 Contrato com o resolver do mercado (Polymarket)

O sistema so e valido se usar o **mesmo** contrato do resolver do mercado.

Definir e congelar:

- Estacao/ICAO exata usada na resolucao (ex.: `NZWN`) e se ha alias.
- Feed/fonte de verdade (ex.: WU/airport station, aviationweather, etc.) e como mapear para o inteiro final.
- Janela do "dia" (00:00-23:59 local, ou outra) e tratamento de timezone/DST.
- Tratamento de METAR ausente e eventos especiais (ex.: SPECI).

Este contrato deve ser verificado por um "miner" de dados (ex.: 30-60 dias) que compare decimais vs inteiro publicado, para inferir `Q(x)` bit-a-bit.

### 2.3 Loss band-aware (treino)

Treinar modelos com loss compatível com resolução inteira:

- Erro = 0 se `ŷ ∈ B(k)`
- Penalidade cresce fora da banda
- Variantes: penalidade linear vs quadrática fora da banda (experimentar e medir)

## 3) Dados e causalidade (time contracts)

### 3.1 Checkpoints (CP-aware)

Cada previsão em CP deve usar apenas dados disponíveis até aquele instante. Regras:

- Sem uso de t > CP em features
- Rolling windows devem ser estritamente passadas (equivalente a `closed='left'`)
- Nunca usar `≤ t` onde o correto é `< t`

### 3.2 Fontes (alto nível)

- Observações: METAR (e opcionalmente TAF como input exógeno, se for provado útil)
- Baselines: NWP ensemble (múltiplos modelos) + climatologia horária

### 3.4 TAF (input exogeno) - onde entra e como usar

Problema: o dataset historico principal pode nao conter TAF. Mesmo assim, um parser de TAF e valioso como **mais uma previsao** para:

- alertas de mudanca de regime (clearing, chuva, mudança de vento)
- features exogenas para o core (somente se passar gates)
- modulador de confianca / stay-out quando TAF sinaliza transicao/instabilidade

Contrato de causalidade (anti-leakage):

- Em cada CP, so usar TAFs que existiam e eram publicos **ate o CP**.
- Proibido usar em backtest o "TAF final do dia" se ele foi emitido depois do CP.
- Guardar metadados: `issued_time_utc`, `valid_from_utc`, `valid_to_utc`, `station`.

Integracao recomendada (arquitetura):

1) **Ingestao** (Fase 1/2): baixar TAF bruto e salvar snapshot (bit-for-bit) + SHA256, igual ao METAR.

2) **Parsing**: transformar TAF em uma sequencia de segmentos (TEMPO/BECMG/PROB) com janelas de validade.

3) **Features derivadas por CP** (todas causais):

- flags: `taf_has_rain`, `taf_has_showers`, `taf_has_thunder`, `taf_has_clearing` (ex.: aumento de vis/ceiling)
- vento: direcao/forca prevista por janela; mudanca esperada (delta) nas proximas H horas
- nuvens: ceiling minima prevista, probabilidade de deterioracao/melhoria
- transicao: "tem mudanca relevante nas proximas 3-6h" (binario + score)
- consistencia com NWP: disagreement TAF vs NWP (sinal de incerteza)

4) **Uso operacional (ordem de seguranca)**:

A) Primeiro como *alerta/feature de confidence* (baixo risco)

B) Depois como feature no residual learning (alto risco) somente se ganhar fora-da-amostra e nao violar gates.

Validacao:

- Avaliar incrementalmente: baseline core sem TAF vs core + TAF (ablation) em expanding-window.
- O TAF deve melhorar pelo menos uma metrica-alvo (bracket-match ou calibracao/coverage ou accuracy-vs-coverage) sem degradar gates.
- Auditar explicitamente timestamps de emissao/validade (parte do Frozen observation test).

### 3.3 Integridade

- Versionamento e hash dos artefatos (SHA256) antes de inferência
- Cache/retry/flags de `data_quality` quando inputs faltarem

## 4) Arquitetura do sistema (módulos)

### 4.1 Pipeline de forecast (core)

Objetivo: produzir distribuição por bracket/inteiro e medidas de incerteza.

Etapas recomendadas (conceituais):

1) **Feature engineering** (causal, CP-aware)

2) **Modelo base** em delta vs climatologia horária smoothed

3) **NWP baseline + correção (residual learning)**

- NWP como baseline; ML aprende erro/bias condicionado (hora/estação/regime/spread)
- alternativa: blend convexa com β auditado

4) **Calibração** (conformal/quantis empíricos) para IC nominal (ex.: 80%)

- Preferir conformal/empirico antes de adicionar corretor online.

5) **Correção online de drift (opcional, apenas Fase 6)**

- AR(7) residual por CP so entra apos provar ganho marginal e ausencia de leakage.

Saídas mínimas por CP:

- `P(Tmax = k)` ou `P(bracket_i)`
- `P50_k` (inteiro) e `IC80` (no espaço correto)
- métricas de confiança (ver seção 6)
- hashes de artefatos + data_quality

### 4.2 Módulo de late spike (separado)

Objetivo: estimar risco de revisão tardia que destrói NO “resolvido” e cria edge em 1-cent.

Definir um label principal (escolher 1 como v1):

- L1: `CrossThresholdAfterCP` (cruza para o próximo inteiro/bracket após CP operacional)
- Alternativas: `NewTmaxAfterCP`, `LateSpikeSize≥Δ`

Saídas:

- `spike_risk` calibrado (probabilidade)
- flags para bloqueio de trades (ver seção 7)

Features típicas (sempre causais):

- travão/platô (tempo desde novo máximo, slopes)
- vento/regime change, pressão/tendência
- nuvens/clearing, pós-chuva/umidade (proxies)
- spread/discordância NWP (proxy de risco)

## 5) Avaliação e auditoria (gates)

### 5.1 Split temporal

Obrigatório: expanding-window (≥ 3 splits) + métricas por CP.

### 5.2 Baselines obrigatórios

- Persistência (especialmente em k=1h)
- Climatologia horária smoothed
- NWP cru / ensemble

### 5.3 Gates anti-nowcaster (mínimo)

Manter um conjunto de gates no estilo §7, incluindo:

- Skill vs persistência (k=1h, k=3h) por CP
- `corr(ŷ, truth) > corr(ŷ, now)` (forecaster vs nowcaster)
- importância/uso de observação corrente não dominante
- calibração (cobertura IC80 dentro de tolerância)
- testes de cauda (erros grandes/late spike)

### 5.4 Métricas principais (alinhadas ao mercado)

- Bracket/inteiro match no CP operacional
- Accuracy vs coverage (seleção por confiança)
- RPS/ECE no espaço de brackets
- Métricas específicas de late spike: PR-AUC, recall@low-FPR, calibração do spike_risk

### 5.5 Auditoria forense anti-nowcasting (protocolo destrutivo)

Objetivo: tentar **destruir** o modelo e testar H0: “o modelo não antecipa dinâmica; apenas reage à temperatura observada”.

Regras:

- Walk-forward (splits temporais), sem validação randomizada
- Sempre comparar contra persistência
- Sempre segmentar por dificuldade (spikes, regimes, CPs)
- Sempre reportar ICs (bootstrap) e testes de significância quando aplicável

Fases (alto nível):

1. **Lead-time forecast audit**: performance vs lead-time antes de spikes (ΔT ≥ 2/3/4°C), com ROC/PR-AUC, Brier, CRPS/RPS, reliability por lead.
2. **Frozen observation test**: auditoria de causalidade por feature (último timestamp usado vs CP) + verificação de rolling/overlap.
3. **Counterfactual same-temp test**: pares com mesma temperatura observada, regimes diferentes → separabilidade (AUC, Wasserstein/KL).
4. **No-temperature model**: remover âncoras térmicas diretas e medir skill residual (prova de informação atmosférica).
5. **Horizon degradation**: curvas por CP (quanto cedo piora, quanto tarde melhora) sem “explodir” apenas no fim do dia.
6. **Extreme spike audit**: cauda (top 1%/5% ΔT), calibração condicional e tail scores.
7. **Economic edge validation (shadow trading)**: EV esperado vs realizado, calibração por buckets de EV, drawdown.

Este protocolo deve existir como um script/relatório reproduzível no repositório (não como texto).

## 6) Confiança (selective forecasting)

Objetivo: não “acertar sempre”, mas ser **muito bom quando confiante**.

Definir um `confidence_score` calibrado para `P(acerto do inteiro/bracket)`.

Sinais recomendados:

- entropia da distribuição de brackets
- largura do IC (ex.: IC80)
- spread/disagreement do ensemble NWP
- estabilidade CP-a-CP (convergência)
- margem até limiar do inteiro (distance-to-threshold)
- spike_risk (late spike derruba confiança)

Avaliação: curvas accuracy-vs-coverage e risk-vs-coverage.

### 6.1 Auditoria do confidence_score (obrigatorio)

O `confidence_score` deve ser calibrado contra `P(bracket_correct)` em hold-out temporal.

Requisitos minimos:

- Reportar ECE do confidence_score (ex.: ECE <= 0.05) em split temporal.
- Reportar tabela obrigatoria: bracket-match @ coverage em {25%, 50%, 75%, 100%}.
- Falha nesta auditoria implica que o confidence_score nao pode ser usado como gate (stay-out) em producao.

## 7) Decisão de trade (YES/NO + stay-out)

### 7.1 Princípios

- O sistema deve sempre computar YES e NO (complementares) e comparar com preços.
- “NO-first” como heurística não é suficiente; quando NO já está 0.99+, geralmente não há edge.

### 7.2 Três estados operacionais

A) **Resolvido sem edge** (ex.: NO muito caro) → NO TRADE  

B) **Armadilha de late spike** (NO caro + spike_risk) → bloquear BUY NO  

C) **Oportunidade assimétrica** (YES 1-cent com probabilidade real > preço) → candidato a trade pequeno

### 7.3 Bloqueios mínimos (v1)

- Bloquear BUY NO quando `spike_risk` alto e/ou margem até limiar pequena
- Preferir NO TRADE quando `price_no` já é muito alto

(Thresholds devem ser aprendidos/validados, não escolhidos no feeling.)

### 7.4 Funcao-objetivo para aprender thresholds (obrigatorio)

Aprender/ajustar thresholds exige funcao-objetivo pre-registrada. Escolher uma (ou definir hierarquia):

- max(EV) sujeito a max_drawdown <= X
- max(Sharpe) sujeito a coverage >= X
- max(bracket_match_when_traded) sujeito a coverage >= X

Sem funcao-objetivo, tuning de thresholds e considerado overfit.

## 8) Operação local (orquestrador)

Requisitos:

- CLI única para rodar forecast + postmortem + update (AR)
- exit codes honestos (sem soft-fail)
- logs estruturados (JSON) com tempos, fontes e warnings
- backups e dedupe para estado online (AR)

## 9) Repositório e padrões de engenharia

- Pastas: `core/`, `nzwn/` (config), `experiments/`, `reports/`, `artifacts/`, `tests/`
- Seeds fixas para treinos experimentais
- Golden tests (inputs congelados → outputs esperados)
- Quarentena para backups/scratch

### 9.1 Reverse-import guard (anti-contaminacao)

- Diretorio `audits/` e read-only em relacao a `core/` e `nzwn/`.
- CI deve falhar se qualquer arquivo em `core/` ou `nzwn/` importar `audits` (checagem estatica pre-commit + GitHub Actions).

## 10) Pendências (decisões a fechar)

1) Validar contrato do resolver do mercado (secao 2.4) e confirmar que ele e compativel com o default de `Q(x)`/`B(k)`

2) Escolha do label principal de late spike (L1/L2/L3)

3) Cutoffs operacionais iniciais (ex.: o que é “NO caro/resolvido”) — preferir aprender via backtest

4) Definir CP operacional padrão para NZWN e como medir ganho por CP

## 11) Checklist de refinamento (ideias validadas e como usar)

Esta seção transforma hipóteses/ideias em **regras auditáveis**, para evitar investir em caminhos falhos.

### 11.1 Proibição de leakage (hard rules)

- **Proibido** usar `Tmax(D0)` (verdade do dia) como feature em treino/inferência. Isso é leakage direto.
- A auditoria “Frozen observation test” deve verificar timestamps de **todas** as features e rolling windows.

### 11.2 Cluster/regime analysis (EDA → baseline + feature + alerta)

Usos recomendados, em ordem:

1) **Baseline condicional**: `P(Tmax=k | mês, regime, CP)` e métricas por bucket (serve para provar ganho do ML).

2) **Feature/prior**: regime como input (ou embeddings leves) para capturar física local.

3) **Alerta**: buckets raros/instáveis derrubam `confidence_score` (stay-out).

### 11.3 Distribuição real do horário de Tmax (EDA obrigatória)

EDA deve produzir:

- distribuição e quantis do **horário local do Tmax** por `(mês, regime)`
- taxa de **early peak**
- taxa de “Tmax fora do horário típico” (outliers)

Uso:

- prior/feature (horário típico)
- alerta: risco de dia atípico (baixa confiança)
- suporte ao módulo late spike: spike “fora do horário típico” é risco-chave

### 11.4 Active analog search (analogs) — uso recomendado

Analogs são úteis principalmente para **reduzir incerteza** e melhorar confiança:

- Buscar analogs condicionados por `(mês, regime, CP)` antes de comparar features contínuas
- Produzir saídas: distribuição empírica de `Tmax` e de `late spike` nos analogs

Papéis:

- **camada de incerteza** (não necessariamente o forecaster principal)
- diagnóstico e explicabilidade (“dias parecidos tiveram X% de flip”)

### 11.5 Confidence indication (selective forecasting)

Requisitos:

- `confidence_score` deve ser calibrado para `P(acerto do inteiro/bracket)` (accuracy-vs-coverage).
- Baixa confiança deve implicar **NO TRADE** por padrão.

### 11.6 Late spike (por enquanto como alerta operacional)

Mesmo com foco atual em bracket-match, late spike deve existir como:

- `spike_risk` e alertas que permitem **sair antes** (ex.: vender NO a 0.90 em vez de virar pó).
- EDA deve focar outliers (clearing, pós-chuva, travões, vento, mudança de regime).

## 12) Requisitos de tempo (UTC/local) e cobertura de 24h

### 12.1 Regra de tempo

- Dataset em **UTC**; conversões para horário local devem ser feitas via timezone explícito da estação/cidade.
- Proibido comparar timestamps tz-naive com tz-aware.
- Todos os relatórios devem sempre imprimir: `cp_utc`, `cp_local`, `tz_name`.

### 12.2 Cobertura de 24h (evitar Tmax “na madrugada”)

- Cálculo de Tmax(D0) e de “hora do Tmax” deve analisar **todas as 24h** do dia local (não só janela parcial).
- Definir claramente a janela de “dia local” (ex.: 00:00–23:59 local) e mapear para UTC.

## 13) EDA avançada (intraday e interday)

### 13.1 Mudanças intradiárias de regime

EDA deve medir:

- frequência de transição de regime ao longo do dia
- impacto no erro do forecast (segmentar por “regime mudou vs não mudou”)

### 13.2 Efeitos meteorológicos por regime

Analisar, global e condicional por regime:

- vento (setor + intensidade), cobertura/nuvens/clearing, chuva/pós-chuva, pressão e tendência

### 13.3 Dinâmica entre dias (regime sequences)

EDA deve explorar:

- sequências típicas de regimes (A→B→C) e se elas ajudam a prever risco/viés no dia seguinte
- efeito de `Tmin(D-1)` e `Tmax(D-1)` como features (permitidas por serem passadas), com validação fora-da-amostra

## 14) Operação: logs diários + postmortem (obrigatório)

- Registrar forecast por CP em logs estruturados (JSON) com hashes e `data_quality`.
- Rodar postmortem D+1 automaticamente:
    - truth vs forecast por CP
    - atualização do estado online (AR) quando aplicável

## 15) Ingestão automática (inputs e preços)

Requisitos:

- Fetch automático de METAR (e opcionalmente TAF) com cache+retry+timeouts
- Integração diária/recorrente para:
    - odds/brackets do mercado (por URL de evento)
    - salvar snapshot de preços junto com timestamp e CP

Obs.: cada mercado tem URL; o sistema deve aceitar “eventUrl” como input e extrair os contracts/brackets.

## 16) Calibração (lição do FIRMCalibrator)

Se usar calibradores sazonais:

- exigir janela que cubra **12 meses** (verão + inverno) para evitar calibração míope.
- toda calibração deve ser reavaliada em splits temporais (não “fit uma vez e congelar”).

## 17) Convenções de execução e compatibilidade

### 17.1 Python CLI

- Padrão de comandos e documentação: usar `py` (ex.: `py -3 ...`) como forma principal.

### 17.2 ASCII-only (evitar erros de unicode)

- Evitar caracteres unicode em nomes de arquivos, paths, CLIs e outputs de automação.
- Preferir ASCII em logs estruturados (JSON) e em nomes de artefatos.

## 18) Provas quantitativas anti-"blinding"/nowcasting

Objetivo: impedir que o sistema pareça forecaster apenas por heurísticas de mascaramento ("blinding") enquanto ainda reage a temperatura observada.

Para declarar o modelo como **forecast atmosférico real**, exigir evidência quantitativa (com ICs e baselines):

1) **Distribuição heteroscedástica**: o sistema deve produzir uma distribuição/IC cuja largura varie de forma coerente com o risco (e não uma variância fixa). Avaliar com risk-coverage e sharpness-vs-calibration.

2) **Validação de lead-time vs persistência**: medir skill (e/ou ROC/PR-AUC para spikes) em múltiplos leads antes do evento, sempre contra persistence. O modelo deve manter skill positiva **horas antes** (não apenas "no último minuto").

3) **Modelo atmosférico puro**: treinar/avaliar uma variante sem âncora térmica dominante (sem `tmpc`, `t_so_far`, `Tmax(D-1)`, `Tmin(D-1)` e similares) e verificar se ainda existe skill significativa vs baselines. Se não houver, o modelo principal deve justificar explicitamente por que o ganho vem de informação realmente antecipatória.

Estes requisitos são implementados e reportados no protocolo da seção 5.5 (Auditoria forense anti-nowcasting).

## 19) Ideias testaveis extraidas de projetos de referencia

Objetivo: transformar referencias externas em **experimentos controlados** (cada um com baseline e criterio de aceite), sem copiar atalhos.

### 19.1 Baselines obrigatorios (para todos os experimentos)

- Persistencia (por CP/lead)
- Climatologia horaria smoothed
- NWP cru / ensemble (quando aplicavel)

Regra: toda mudanca deve mostrar ganho fora-da-amostra (walk-forward / expanding-window) e manter gates anti-nowcaster.

### 19.2 Experimentos recomendados (inspirados em A/B/C)

1) **NWP ensemble + disagreement metrics** (Projeto A)

- Implementar features: media ponderada, spread, king-conflict/disagreement.
- Hipotese: spread/disagreement melhora confianca e calibracao; pode melhorar bracket-match via condicionalizacao.
- Aceite: melhora em RPS/ECE e accuracy-vs-coverage, sem regressao de bracket-match.

2) **Distribuicao de erro com caudas (nao-Gaussiana) vs conformal** (Projeto A)

- Testar Student-t (nu fixo) como baseline parametric vs conformal empirico por CP.
- Aceite: melhor sharpness mantendo cobertura nominal e sem degradar bracket-match.

3) **Tabela de bias sazonal estatica (NEGATIVE CONTROL)** (Projeto A)

- Implementar a versao simples (mes x modelo) como controle, sabendo que pode falhar.
- Objetivo: provar quantitativamente se degrada fora-da-amostra (e documentar).
- Aceite: somente se ganhar em 2/3 splits; caso contrario, fica documentado como anti-padrao.

4) **Self-calibration estilo sigma por fonte/cidade (baseline de referencia)** (Projeto B)

- Implementar versao minimalista: estimar escala de erro por CP (ou por bucket) a partir de historico.
- Observacao: evitar "sigma=MAE + normal" como unica distribuicao; usar como baseline/ablation.
- Aceite: melhorar calibracao e/ou bracket-match vs baseline NWP cru.

5) **Nowcast blend com observacao corrente (NEGATIVE CONTROL)** (Projeto A)

- Testar apenas como controle para medir quanto melhora metricas tardias e quanto viola gates anti-nowcaster.
- Aceite: nao pode entrar em producao do core; se passar gates, documentar condicoes especificas.

6) **Pipeline minimalista primeiro (sanity check)** (Projeto B)

- Reproduzir um baseline simples (poucos arquivos/modulos) antes de adicionar complexidade.
- Aceite: baseline reproduzivel com logs, splits e gates (serve como ponto de partida).

7) **Gradient boosting tabular vs ridge (familia funcional)** (Projeto C)

- Testar XGBoost/LGBM vs Ridge, sempre com splits temporais.
- Aceite: ganho maior que variancia amostral (IC bootstrap) e sem regressao em cauda.

### 19.3 Principios de uso (o que copiar vs o que nao copiar)

- Copiar: estrutura modular, logging de snapshots, disagreement/spread, filtros de qualidade.
- Nao copiar: validacao frouxa, p=1.0 placeholder, bias correction congelada sem revalidacao, nowcasting reativo no core.

## 20) Plano de implementacao por fases (com obsessao por leakage)

Objetivo: executar um caminho incremental (baseline -> melhorias), onde cada fase tem **testes, validacao walk-forward** e **auditoria anti-leakage**. Nada entra sem evidência fora-da-amostra.

### 20.0 Regras globais (valem em todas as fases)

- Split: expanding-window (>= 3 splits) + metricas por CP + segmentacao por dificuldade.
- Baselines obrigatorios: persistencia, climatologia horaria smoothed (e NWP cru quando aplicavel).
- Sempre rodar: Frozen observation test + lead-time audit vs persistencia (secao 5.5).
- Toda mudanca: precisa ganhar em >= 2/3 splits e nao regredir gates anti-nowcaster.
- Artefatos: hashes (SHA256), seeds fixas, logs estruturados, ASCII-only.

### Fase 1 - Data contracts + labels + EDA basica (sanity)

Entregaveis:

- Definir `Q(x)` e `B(k)` (quantizacao/bandas) como contrato oficial.
- Definir "dia local" e mapeamento UTC<->local; calcular Tmax e hora do Tmax em 24h completas.
- Dataset builder causal (CP-aware) com testes de timestamp por feature.
- EDA minima: distribuicao de hora do Tmax por mes; baselines de persistencia e climatologia.

Requisito adicional:

- Snapshot deterministico do METAR cru baixado (bit-for-bit) + SHA256. Reprocessamento parte do snapshot, nao do feed (feeds podem revisar retroativamente).

Opcional (se fonte disponivel desde o inicio):

- Snapshot deterministico de TAF bruto + SHA256 e parser minimo (somente estruturacao por segmentos e timestamps).

Testes:

- Testes unitarios de tempo (UTC/local), janela 24h, e regras de causalidade (< CP).
- Golden tests em alguns dias fixos (inputs congelados -> outputs esperados).

Metricas:

- Baselines (persistencia/climatologia) por CP para bracket-match.

### Fase 2 - Baseline minimalista (Projeto B style) + reproducibilidade

Entregaveis:

- Baseline simples e reproducivel: climatologia + (opcional) NWP cru, sem ML complexo.
- Logging de snapshots por CP (forecast, baselines, features agregadas, data_quality).

Testes:

- Reproducibilidade de ponta a ponta (mesma config -> mesmos KPIs).
- Auditoria forense rodando e produzindo relatorio.

Aceite:

- Pipeline roda sem falhas silenciosas; metricas por CP batem baselines esperados.

Extensao (ainda Fase 2):

- TAF entra como **alerta** e como features de confidence (sem entrar no core de previsao), com auditoria de timestamps.

### Fase 3 - Ridge delta-vs-climo + band-aware loss (primeiro ML serio)

Entregaveis:

- Ridge (ou regressao linear) prevendo delta vs climatologia horaria.
- Loss band-aware (zero dentro de B(k)).

Testes/validacao:

- Walk-forward vs persistencia e vs climatologia.
- Gates anti-nowcaster + counterfactual same-temp.

Aceite:

- Ganho consistente em bracket-match no CP operacional (>= 2/3 splits), sem violar 5.5.

### Fase 4 - NWP baseline + residual learning + disagreement/spread

Entregaveis:

- Ensemble NWP + features de spread/king-conflict.
- Modelo de correcao do erro do NWP (residual learning) condicionado por mes/CP/regime/spread e sinais intraday.

Testes/validacao:

- Comparar contra NWP cru e contra Ridge baseline.
- Calibracao (RPS/ECE) e accuracy-vs-coverage.

Aceite:

- Melhorar bracket-match e calibracao sem regredir gates; melhoria maior que variancia amostral (IC bootstrap).

### Fase 5 - Calibracao heteroscedastica (conformal por CP/bucket)

Entregaveis:

- Conformal por CP (e opcionalmente por buckets com n_min).
- Curvas risk-coverage e sharpness-vs-calibration.

Aceite:

- Cobertura IC80 dentro de tolerancia (ex.: 0.80 +/- 0.05) e intervalos mais curtos em dias "faceis".

### Fase 6 - AR online (drift/bias) + backtests de robustez

Entregaveis:

- Corretor online (ex.: AR(7)) estritamente passado, com backups e dedupe.

Validacao:

- Expanding-window CV + testes de drift (pre/post).

Aceite:

- Reduzir bias/drift sem criar leakage; auditoria de timestamps inclui corretor.

### Fase 7 - Late spike como alerta (nao como core) + saida antecipada

Entregaveis:

- `spike_risk` como alerta operacional e como feature de confianca.
- EDA de outliers e buckets de risco por (mes, regime, CP).

Aceite:

- Melhora em accuracy-vs-coverage e reducao de erros graves/flip sem degradar bracket-match.

### Fase 8 - Validacao economica (shadow trading)

Entregaveis:

- Registro de odds/brackets por eventUrl + snapshots.
- EV esperado vs realizado; drawdown; calibracao por buckets de EV.

Aceite:

- Edge realizado consistente com edge esperado (dentro de ICs) e sem dependencia de janelas contaminadas.

## 21) Reforcos (brainstorm) - pontos que precisam virar compromisso antes da Fase 1

Observacao: estes itens vieram de uma analise potencialmente contaminada (baseada em codigo ruim), mas as recomendacoes abaixo sao **estruturais** e valem como hardening do spec.

### 21.1 Fechar decisoes pendentes (nao iniciar Fase 1 sem isso)

1) **Quantizacao oficial** (secao 2.2)

- Default definido: `B(k) = [k-0.5, k+0.5)` e `Q(x) = floor(x + 0.5)`.
- A pendencia passa a ser apenas validar compatibilidade com o resolver (secao 2.4).

2) **Late spike label principal**

- Recomendacao: L1 `CrossThresholdAfterCP` (mapeia diretamente o evento que destrói NO).

3) **CP operacional NZWN**

- Recomendacao: 23Z (11:00 local em Wellington) como CP operacional padrao para metricas principais.

### 21.2 Reprodutibilidade forte (nao apenas "seeds fixas")

Requisitos minimos:

- Fixar seeds de: Python `random`, NumPy, e RNGs de bibliotecas (ex.: LightGBM: `seed`, `bagging_seed`, `feature_fraction_seed` etc.).
- Documentar determinismo CPU vs GPU (GPU off por default, ou documentar diferencas).
- Teste em CI: dois treinos consecutivos (mesmos dados/config) devem produzir artefato com SHA256 identico, ou entao um criterio de tolerancia explicitamente definido.

### 21.3 Gates anti-nowcaster com thresholds pre-registrados

Regra: thresholds devem ser fixados **antes** de olhar resultados do experimento.

Sugestao de thresholds minimos (ajustar se necessario, mas fixar):

- SS(1h) > 0.08 com bootstrap CI95% excluindo 0
- SS(3h) > 0.10 com bootstrap CI95% excluindo 0
- `corr(ŷ, truth) - corr(ŷ, now) >= 0.20`
- `abs(coverage_80 - 0.80) < 0.04`
- `I_T_obs < 0.10`
- AUC contrafactual (same-temp) > 0.70
- ACF(residuos): nenhum lag significativo ate 7

### 21.4 NWP forecast vs NWP archive (hard rule)

- O treino/avaliacao deve usar o **forecast** que estaria disponivel no CP (historical-forecast), nao reanalysis/"archive" que incorpora verdade retrospectiva.
- O pipeline deve salvar snapshots por timestamp do run (fonte, modelo, lead) para auditoria.

### 21.5 DST Wellington (teste unitario obrigatorio)

- Sempre usar `zoneinfo.ZoneInfo("Pacific/Auckland")`.
- Adicionar teste unitario com timestamps ao redor da mudanca de DST (ex.: inicio/fim de DST) para garantir mapeamento UTC->local correto.

### 21.6 Thermo-anchor coasting (gate adicional)

- Se `Tmax(D-1)` / `Tmin(D-1)` forem usados como features, monitorar importancia.
- Regra sugerida: se permutation importance de `Tmax(D-1)` > 0.10, tratar como violacao (modelo esta "coasting" por autocorrelacao diaria).

### 21.7 Budget de complexidade (evitar modulos zumbis)

- Cada modulo/feature-set precisa de um criterio de exclusao: se nao entregar ganho >= X (acima da variancia amostral) em N semanas/iteracoes, deve ser removido.

### 21.8 Kill criterion por fase (nao pular para complexidade)

- Se a Fase 3 (Ridge band-aware) nao bater baselines em >= 2/3 splits, **parar** e revisitar features/dados/labels (nao seguir para Fase 4).

### 21.9 Selective forecasting: pontos discretos obrigatorios

- Em todo relatorio/postmortem incluir tabela: bracket-match @ coverage em {25%, 50%, 75%, 100%}.

### 21.10 Regimes: compromisso concreto (evitar clusters ad-hoc)

- Definir regime como clustering fixo (ex.: GMM 6-8 grupos) em variaveis simples ao amanhecer (vento_dir, vento_int, QNH, tendencia).
- Treinar uma vez (em treino), congelar em producao; proibido criar nomes/clusterizacoes novas por sprint.

### 21.11 Calibracao: separar regra sazonal vs conformal

- Calibradores sazonais (tipo FIRM) exigem janela >= 12 meses.
- Conformal por CP/bucket pode usar janela curta (ex.: 60-90 dias), mas deve ser auditada.

### 21.12 Prova de heteroscedasticidade (teste concreto)

- Bin dos forecasts por largura do IC estimado (quartis) e verificar cobertura empirica por bin.
- IC pequeno nao pode ter cobertura muito maior que IC grande; caso contrario e ruido/erro de calibracao.

### 21.13 Self-calibration em single-city

- Reformular "sigma por fonte/cidade" como escala por (CP, fonte) ou apenas por CP; evitar nomenclatura multi-cidade no escopo NZWN.

## 22) Saidas obrigatorias de auditoria (verdict file)

Cada execucao do protocolo da secao 5.5 deve emitir:

- `audits/<run_id>/h0_verdict.json` contendo:
    - `H0_rejected: bool`
    - `criterion: str`
    - `criterion_version: str`
    - `evidence_per_phase: [...]`

Sem este arquivo, a execucao da auditoria e considerada FAIL.

## 23) Anti-padroes historicos (lista de proibicoes com justificativa)

Objetivo: defesa contra recidiva. Cada item abaixo deve ter teste/checagem associada.

- Usar `Tmax(D0)` como feature (leakage direto)
- Bias correction estatica (.pkl) sem revalidacao temporal
- Calibrador sazonal (ex.: FIRM) com janela < 12 meses
- Soft-fail (exit 0 com zero forecasts gerados)
- Rolling/agregacao com janela contaminada (ex.: closed='right' ou shift(0))
- Previsao sem flag `data_quality`
- Metricas agregadas globais sem segmentacao por dificuldade
- Usar NWP archive/reanalysis como se fosse forecast disponivel no CP

## 24) Metricas do produto (primaria vs gates)

Para evitar ambiguidade:

- **Metrica primaria (v1):** `EV_realizado_no_test_split` em shadow trading (secao 5.5 fase 7 / secao 20 Fase 8).
- Metricas como bracket-match, RPS, ECE, SS vs persistencia sao **gates necessarios**, nao suficientes.

Regra: um modelo que melhora RPS/bracket-match mas piora EV realizado (fora-da-amostra) e rejeitado.

## 25) Notas de arquitetura (ajustes)

1) **Residual learning sobre NWP** e a abordagem preferida para o core.

2) **Blend convexo com beta** nao e candidato a producao do core; manter apenas como baseline/controle em experimentos.

3) **AR online** so pode ser promovido com:

- backup antes de cada update
- DM-test/validacao walk-forward vs persistencia
- flag para desabilitar se cobertura/calibracao piorar

## 26) Implementation plan (backlog acionavel) alinhado ao spec

Objetivo: transformar as Fases (secao 20) em um backlog executavel, com entregaveis, testes e criterio de aceite.

### 26.1 Setup inicial (Dia 0)

- [ ]  Criar estrutura de repo: `core/`, `nzwn/`, `audits/`, `experiments/`, `reports/`, `artifacts/`, `tests/`, `references/legacy/`.
- [ ]  CI baseline: lint + tests + reverse-import guard (secao 9.1) + ASCII checks.
- [ ]  Definir convencoes de CLI (`py -3 ...`) e logging JSON.

Aceite:

- CI verde no commit inicial e bloqueia import proibido (`core/`/`nzwn/` -> `audits/`).

### 26.2 Epic A - Contratos e verdade (Fase 1)

Entregaveis:

- [ ]  `contracts/quantization.md`: Q/B definidos (secao 2.2) + exemplos.
- [ ]  `contracts/resolver.md`: contrato com resolver (secao 2.4): estacao, feed, janela do dia, missing METAR/SPECI.
- [ ]  Dataset builder CP-aware (METAR) + snapshot bruto + SHA256 (secao 20 Fase 1).
- [ ]  Testes: timezone (Pacific/Auckland), DST, 24h window, causalidade (< CP), golden tests.

Aceite:

- Rodar duas vezes gera o mesmo snapshot (hash igual) e o mesmo dataset derivado.
- Frozen observation test passa para baselines (sem usar futuro).

### 26.3 Epic B - Baselines reproduziveis + harness de auditoria (Fase 2)

Entregaveis:

- [ ]  Baselines: persistencia + climatologia horaria smoothed (+ opcional NWP cru, se ja disponivel).
- [ ]  Runner unico: `forecast` e `postmortem` gerando relatorios por CP.
- [ ]  Implementar o protocolo 5.5 como executavel sobre baselines.
- [ ]  Output obrigatorio: `audits/<run_id>/h0_verdict.json` (secao 22).

Aceite:

- Auditoria roda em baselines e produz verdict file; sem soft-fail.

### 26.4 Epic C - TAF como alerta (ainda Fase 2)

Entregaveis:

- [ ]  Ingestao snapshot de TAF bruto + SHA256 (se fonte disponivel).
- [ ]  Parser TAF -> segmentos com (issued_time, valid_from/to) + features de transicao.
- [ ]  Integrar em `confidence_score` como *alerta* (nao no core).
- [ ]  Auditoria de timestamps do TAF (issued_time <= CP).

Aceite:

- Em backtest, nenhum TAF emitido apos o CP aparece nas features.

### 26.5 Epic D - Primeiro ML (Fase 3)

Entregaveis:

- [ ]  Ridge delta-vs-climo + loss band-aware.
- [ ]  Walk-forward expanding-window (>=3 splits) + IC bootstrap.
- [ ]  Gates pre-registrados (secao 21.3) implementados como checks que podem falhar o build.

Aceite:

- Bate baselines em >= 2/3 splits, com ganho acima da variancia amostral.
- Se falhar: parar e revisitar features/dados (nao iniciar Fase 4).

### 26.6 Epic E - NWP residual learning + disagreement/spread (Fase 4)

Entregaveis:

- [ ]  NWP ingestion: usar forecast historico disponivel no CP (nao archive), com snapshots.
- [ ]  Residual learning + features de spread/disagreement.
- [ ]  Ablations: NWP cru vs NWP+residual vs Ridge.

Aceite:

- Melhora bracket-match + calibracao sem violar gates e com ganho acima do ruido.

### 26.7 Epic F - Calibracao e confidence (Fase 5)

Entregaveis:

- [ ]  Conformal por CP/bucket (janela curta auditada).
- [ ]  Auditoria do confidence_score (secao 6.1): ECE <= 0.05 + tabela coverage.
- [ ]  Teste de heteroscedasticidade por bins de largura do IC (secao 21.12).

Aceite:

- Cobertura IC80 dentro da tolerancia + confidence audit passa.

### 26.8 Epic G - AR online (Fase 6, opcional)

Entregaveis:

- [ ]  AR com backup + rollback.
- [ ]  DM-test / validacao walk-forward vs persistencia.
- [ ]  Feature-flag para desabilitar em producao.

Aceite:

- Somente promover se ganho consistente e sem sinais de leakage.

### 26.9 Epic H - Late spike como alerta (Fase 7)

Entregaveis:

- [ ]  Label L1 `CrossThresholdAfterCP` + dataset e relatorios.
- [ ]  `spike_risk` calibrado + uso como gate de bloqueio/stay-out.

Aceite:

- Reduz flips/erros graves e melhora accuracy-vs-coverage sem piorar bracket-match.

### 26.10 Epic I - Shadow trading / EV (Fase 8)

Entregaveis:

- [ ]  Ingestao de odds/brackets + snapshots por CP.
- [ ]  Backtest de execucao (shadow) + EV realizado + drawdown.
- [ ]  Otimizacao de thresholds com funcao-objetivo pre-registrada (secao 7.4).

Aceite:

- EV realizado consistente fora-da-amostra e alinhado a calibracao/coverage.