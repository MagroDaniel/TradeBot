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

## Próximos passos (nenhum feito ainda — decisão em aberto)

1. **Reconsiderar a abordagem, não só o parâmetro**: a pesquisa aponta que forex se comporta
   mais como reversão à média que como tendência a maior parte do tempo — uma estratégia de
   mean reversion (Bollinger Bands + RSI, fadar extremos em vez de seguir cruzamento) ataca
   essa causa raiz diretamente, em vez de tentar consertar uma estratégia de tendência com mais
   filtro. É esforço maior (indicador novo, gerador de sinal novo, não reaproveita
   `generate_signal` existente) mas é o candidato mais promissor pela pesquisa.
2. Testar mais combinações em cima do que já funciona (sessão + tendência 4h + algum terceiro
   filtro) — risco crescente de overfitting quanto mais se testa na mesma amostra única (só
   EUR/USD); qualquer nova tentativa precisa passar pelas 3 janelas antes de confiar, mesmo
   padrão usado acima.
3. Ou considerar esse caminho fechado por ora.

Infraestrutura (indicadores, engine de backtest sem viés de look-ahead, cliente da Twelve Data,
storage, Telegram, CLI com --timeframe/--higher-timeframe configuráveis, filtro de sessão)
está pronta e testada (105 testes) pra qualquer um dos três caminhos.

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
