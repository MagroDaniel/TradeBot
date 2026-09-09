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

## Próximos passos (nenhum feito ainda — decisão em aberto)

1. Testar parâmetros recalibrados especificamente pra forex (RSI mais estreito, ATR menor,
   timeframe maior tipo 1h em vez de 15min, R:R diferente) — pesquisa nova, não uma adaptação
   direta do que funcionou em cripto.
2. Ou considerar esse caminho fechado por ora — forex pode exigir uma estratégia diferente do
   EMA/RSI, não só um ajuste de parâmetro.

Infraestrutura (indicadores, engine de backtest sem viés de look-ahead, cliente da Twelve Data,
storage, Telegram) está pronta e testada (103 testes) pra qualquer um dos dois caminhos.

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
