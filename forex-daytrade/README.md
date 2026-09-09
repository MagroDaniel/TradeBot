# forex-daytrade

Bot de sinais técnicos pra pares de forex (câmbio), mesmo método do `crypto-daytrade/`
(EMA9/EMA21 + RSI + stop/alvo por ATR), adaptado pra Twelve Data como fonte de candles em vez
da Binance. Mesma filosofia: **alerta só, nunca executa nada, nunca sugere alavancagem**.

## Status atual (2026-09-09) — baseline testada e REPROVADA, não vai pra produção

Backtest rodado contra histórico real de EUR/USD (60 e 180 dias, Twelve Data) usando o mesmo
processo de validação do `crypto-daytrade`: a estratégia **não tem edge em forex do jeito que
está calibrada hoje** (parâmetros herdados do cripto — RSI 30-65/35-70, ATR 1.5x, R:R 2:1).

| Janela | variante | sinais | win% | R líq | PF líq |
|---|---|---|---|---|---|
| 60d | sem filtro (baseline) | 181 | 19.4% | -0.72 | 0.32 |
| 60d | + tendência 1h | 109 | 11.3% | -1.03 | 0.15 |
| 60d | + ADX ≥ 25 | 79 | 9.3% | -1.16 | 0.13 |
| 180d | sem filtro (baseline) | 526 | 20.6% | -0.68 | 0.34 |
| 180d | + tendência 1h | 288 | 14.3% | -0.91 | 0.21 |
| 180d | + ADX ≥ 25 | 237 | 13.2% | -1.01 | 0.19 |

**Achado principal**: diferente do cripto (onde o filtro de 1h reverteu uma expectância
levemente negativa pra positiva), em forex **todo filtro testado piora o resultado**, não
melhora — o baseline já cru fica pior conforme filtra mais. Consistente nas duas janelas (não
inverteu, amostra cresceu de 181→526 sinais mantendo a mesma direção), então não é ruído de
amostra pequena.

Com R:R fixo em 2:1, o breakeven exige win rate ≥ 33,3%; todas as variantes testadas ficaram
entre 5,5% e 20,6% — muito abaixo. Hipótese mais provável: os parâmetros (RSI, múltiplo de ATR,
timeframe de 15min) foram calibrados pra volatilidade de cripto, que é bem maior que a de um
par major de forex — cruzamento de EMA9/21 no 15min provavelmente está gerando ruído demais no
"chop" característico de EUR/USD, não sinal real.

**Decisão**: bot **não vai pra produção** nessa configuração. Nenhuma mudança de estratégia
some sem validação — mesma regra do `crypto-daytrade`.

## Tentativa de recalibração (2026-09-09, mesmo dia) — melhorou, mas não o suficiente

Usuário pediu pra tentar recalibrar os parâmetros especificamente pra forex em vez de fechar o
caminho. Testado contra 3 janelas (60/180/365 dias) no timeframe de 1h (era 15min) + filtro de
tendência de 4h (era 1h) — hipótese: candle de 15min é ruidoso demais pra forex, volatilidade
bem menor que cripto ("chop"/mean-reversion).

**Achado real, confirmado nas 3 janelas sem inverter**: trocar o timeframe de sinal de 15min
pra 1h melhora a baseline de forma consistente — R líquido foi de ~-0.70 (15min) pra ~-0.35
(1h) nas 3 janelas. Genuíno, não é ruído.

**Achado que NÃO se sustentou — lição sobre overfitting**: a combinação "+ tendência 4h + RSI
estreito (40-60)" parecia muito promissora nas janelas menores (60d: win 38.5%, R líq **-0.03**;
180d: win 34.1%, R líq **-0.14** — quase zero a zero), mas na janela de 365 dias **reverteu**
pra perto da baseline (win 26.0%, R líq **-0.31**) — o mesmo padrão de red flag que já
descartou candidatos em `crypto-daytrade` (resultado bom em amostra pequena que piora conforme
a amostra cresce = provável ruído estatístico, não edge real). Amostra: 18→53→90 sinais.

| Janela | variante | sinais | win% | R líq |
|---|---|---|---|---|
| 60d | baseline (1h) | 40 | 24.2% | -0.31 |
| 60d | + tendência 4h + RSI estreito | 18 | 38.5% | **-0.03** |
| 180d | baseline (1h) | 137 | 25.4% | -0.31 |
| 180d | + tendência 4h + RSI estreito | 53 | 34.1% | -0.14 |
| 365d | baseline (1h) | 244 | 21.6% | -0.40 |
| 365d | + tendência 4h + RSI estreito | 90 | 26.0% | -0.31 |

**Conclusão honesta**: mesmo depois de recalibrar, **nenhuma variante testada até agora cruzou
pra expectância positiva** de forma consistente nas 3 janelas — o timeframe de 1h é uma
melhoria real, mas "menos ruim" não é "lucrativo". Bot continua **fora de produção**.

## Pesquisa + filtro de sessão de horário (2026-09-09, mesmo dia) — melhora real, mas insuficiente

Usuário pediu pra pesquisar mais sobre forex e testar as descobertas. Achados da pesquisa:

- Forex passa **70-80% do tempo em consolidação/range** — mean reversion costuma superar
  trend-following em pares major (o oposto do que EMA crossover assume).
- A liquidez de EUR/USD se concentra nas sessões de **Londres+NY** (aprox. 07h-21h UTC, pico no
  overlap 12h-16h UTC) — fora disso (madrugada UTC, só Tóquio aberto) é onde mais se espera
  ruído puro.
- Crossover de médias estruturalmente soma dois indicadores atrasados — funciona bem em
  tendência, whipsaw garantido em range, sem solução só de parâmetro.

Testado (timeframe 1h) um filtro novo — `session_hours_utc` — que só aceita sinal cujo candle
de abertura cai dentro da janela de horário informada, nas 3 janelas de sempre:

| Janela | variante | sinais | win% | R líq |
|---|---|---|---|---|
| 60d | baseline (1h) | 40 | 24.2% | -0.31 |
| 60d | + tendência 4h | 22 | 29.4% | -0.24 |
| 60d | + sessão overlap (12-16 UTC) | 17 | 7.1% | -0.77 |
| 60d | + sessão Londres+NY (07-21 UTC) | 33 | 25.9% | -0.27 |
| 60d | + sessão Londres+NY + tendência 4h | 15 | 33.3% | **-0.13** |
| 180d | baseline (1h) | 137 | 25.4% | -0.31 |
| 180d | + tendência 4h | 66 | 32.1% | -0.19 |
| 180d | + sessão overlap (12-16 UTC) | 49 | 23.1% | -0.36 |
| 180d | + sessão Londres+NY (07-21 UTC) | 102 | 31.4% | -0.16 |
| 180d | + sessão Londres+NY + tendência 4h | 49 | 37.2% | **-0.07** |
| 365d | baseline (1h) | 244 | 21.6% | -0.40 |
| 365d | + tendência 4h | 112 | 24.7% | -0.35 |
| 365d | + sessão overlap (12-16 UTC) | 75 | 19.4% | -0.45 |
| 365d | + sessão Londres+NY (07-21 UTC) | 179 | 26.1% | -0.28 |
| 365d | + sessão Londres+NY + tendência 4h | 82 | 31.0% | **-0.18** |

**Diferença importante em relação à tentativa anterior (RSI estreito)**: aquela parecia ótima
em amostra pequena e reverteu — overfitting puro. Esta não: **em toda janela, "sessão
Londres+NY" é melhor que a baseline, e "sessão + tendência 4h" é melhor que "tendência 4h"
sozinho — sem inverter uma vez sequer.** É uma melhoria real, não ruído. Curiosamente, o
overlap (12-16 UTC) sozinho piora consistentemente — mais estreito não é melhor aqui, o
contrário do que a intuição sugeriria.

**Mas ainda não é suficiente**: mesmo a melhor combinação (sessão + tendência 4h) continua com
R líquido negativo nas 3 janelas (-0.13, -0.07, -0.18) — progresso real, mas não cruza pra
expectância positiva. Bot continua **fora de produção**.

## Estratégia de reversão à média — Bollinger+RSI (2026-09-09, mesmo dia) — a mais próxima até agora

Implementada do zero (`analysis/mean_reversion_signals.py` + `backtest/mean_reversion_engine.py`
+ `backtest/run_mean_reversion.py`) e testada nas 3 janelas de sempre, timeframe 1h:

| Janela | variante | sinais | win% | R líq |
|---|---|---|---|---|
| 60d | baseline (sem filtro) | 42 | 39.5% | **-0.02** |
| 60d | + sessão Londres+NY | 34 | 36.7% | -0.04 |
| 60d | + RSI 25/75 | 24 | 30.0% | -0.11 |
| 60d | + BB 2.5 desvios | 31 | 35.7% | -0.10 |
| 180d | baseline (sem filtro) | 120 | 34.3% | **-0.08** |
| 180d | + sessão Londres+NY | 97 | 29.3% | -0.17 |
| 180d | + RSI 25/75 | 61 | 30.2% | -0.15 |
| 180d | + BB 2.5 desvios | 90 | 32.9% | -0.08 |
| 365d | baseline (sem filtro) | 238 | 28.4% | **-0.20** |
| 365d | + sessão Londres+NY | 197 | 26.2% | -0.25 |
| 365d | + RSI 25/75 | 127 | 26.6% | -0.18 |
| 365d | + BB 2.5 desvios | 171 | 26.6% | -0.26 |

**A baseline (sem nenhum filtro extra) é o melhor resultado da sessão inteira** — todo filtro
testado em cima dela piora, ao contrário do que aconteceu com o cruzamento de EMA (onde filtro
ajudava). Comparado com o melhor candidato de tendência (sessão + tendência 4h: -0.13/-0.07/
-0.18 nas mesmas 3 janelas), a baseline de mean reversion é igual ou melhor em 2 das 3 janelas
(-0.02 e -0.08), **sem precisar de nenhum filtro extra** — sinal de que a abordagem em si (não
só o parâmetro) está mais alinhada com o comportamento real do mercado.

**Ressalva honesta**: R líquido piora conforme a amostra cresce (-0.02 → -0.08 → -0.20) — o
mesmo tipo de padrão que já vi virar ruído antes (RSI estreito + tendência). Diferença aqui: é
a baseline de uma abordagem nova, não uma combinação escolhida a dedo entre várias testadas, o
que reduz (não elimina) o risco de ser sorte de amostra pequena. Ainda **não é lucrativo em
nenhuma das 3 janelas** — bot continua fora de produção.

## Balanço geral de tudo testado nesta sessão (2026-09-09)

| Abordagem | melhor R líq (60d / 180d / 365d) |
|---|---|
| Cruzamento EMA, 15min (herdado do cripto) | -0.72 / -0.68 / -0.70 (aprox.) |
| Cruzamento EMA, 1h + sessão + tendência 4h | -0.13 / -0.07 / -0.18 |
| Reversão à média (Bollinger+RSI), 1h, baseline | **-0.02** / -0.08 / -0.20 |

## Próximos passos (nenhum feito ainda — decisão em aberto)

1. Testar mean reversion em mais pares (GBP/USD, USD/JPY) — se a mesma baseline funcionar
   melhor em outro par, é sinal de edge real de abordagem, não coincidência de um símbolo só.
2. Refinar o alvo de mean reversion (hoje é a banda central CONGELADA no momento do sinal —
   simplificação deliberada; um alvo dinâmico, que acompanha a banda central se movendo, pode
   capturar mais lucro numa reversão forte).
3. Testar outros timeframes pra mean reversion (15min, 4h) — só foi testado em 1h até agora.
4. Ou considerar esse caminho fechado por ora — depois de 3 abordagens testadas (baseline
   herdada, recalibração de tendência, mean reversion), nenhuma cruzou pra expectância
   positiva de forma consistente nas 3 janelas.

Infraestrutura (indicadores — incluindo Bollinger Bands agora —, dois motores de backtest sem
viés de look-ahead, cliente da Twelve Data, storage, Telegram, CLIs configuráveis) está pronta
e testada (124 testes) pra qualquer um dos quatro caminhos.

## Decisões já tomadas

- **Mesmo bot/grupo do Telegram do `crypto-daytrade`** (não um separado) — reaproveita
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
- **Fonte de dados: Twelve Data** (free tier, 800 chamadas/dia) — OANDA (plano A, dava acesso
  a histórico desde 2005 e spread real) não aceitou cadastro novo do Brasil na divisão
  "Global Markets" no momento da pesquisa.
- **Só EUR/USD pra começar** — cabe folgado na cota diária mesmo escaneando a cada 10 min.
- **Baseline (parâmetros herdados do cripto) reprovada em 2 janelas** — ver "Status atual".

## Comandos

```bash
cd forex-daytrade
pip install -r requirements.txt
python -m pytest -q          # roda sem .env, sem rede
python -m backtest.run --days 60   # precisa de .env (TWELVEDATA_API_KEY)
```
