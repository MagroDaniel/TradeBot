# forex-daytrade

Bot de sinais técnicos pra pares de forex (câmbio), mesmo método do `crypto-daytrade/`
(EMA9/EMA21 + RSI + stop/alvo por ATR), adaptado pra Twelve Data como fonte de candles em vez
da Binance. Mesma filosofia: **alerta só, nunca executa nada, nunca sugere alavancagem**.

## Status atual (2026-09-09)

Módulo recém-criado, ainda **não validado via backtest e não rodando ao vivo**. O que existe
até agora:

- Indicadores, geração de sinal, resolução de stop/alvo, storage e notificação Telegram —
  portados de `crypto-daytrade/`, mesma lógica, testes adaptados (74 testes passando, sem
  rede — ver `tests/`).
- Cliente da Twelve Data (`data/twelvedata_client.py`) — validado manualmente contra a API
  real (chave funcional, candle de EUR/USD 1h retornado corretamente).
- **Diferença importante em relação ao cripto**: os filtros de tendência de timeframe maior e
  de range por estrutura de preço, validados pra cripto via backtest, começam **desligados**
  aqui (`config.USE_HIGHER_TIMEFRAME_FILTER=false`, `MIN_RANGE_EXPANSION=` vazio) — os
  limiares foram calibrados pra volatilidade de cripto, não têm validade garantida pra forex.
  Nada muda esse default sem passar pelo mesmo processo de backtest contra dado real de forex
  primeiro (mesma regra do projeto, ver `crypto-daytrade/CLAUDE.md`).

## Próximos passos (nenhum feito ainda)

1. Construir `backtest/` (engine + histórico + relatório), mesmo padrão de
   `crypto-daytrade/backtest/`, mas já partindo do engine sem viés de look-ahead (entrada no
   candle seguinte, não no fechamento do candle de sinal) — a correção que o cripto só
   recebeu depois de já estar em produção.
2. Rodar o baseline (cruzamento puro, sem filtro) contra histórico real de EUR/USD via
   Twelve Data, pra ver se a estratégia tem expectância positiva nesse mercado antes de
   cogitar ir ao vivo.
3. Só depois decidir sobre `main.py` rodando de verdade (cron do GitHub Actions) — nenhum
   workflow de produção existe ainda pra este módulo.

## Decisões já tomadas

- **Mesmo bot/grupo do Telegram do `crypto-daytrade`** (não um separado) — reaproveita
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
- **Fonte de dados: Twelve Data** (free tier, 800 chamadas/dia) — OANDA (plano A, dava acesso
  a histórico desde 2005 e spread real) não aceitou cadastro novo do Brasil na divisão
  "Global Markets" no momento da pesquisa.
- **Só EUR/USD pra começar** — cabe folgado na cota diária mesmo escaneando a cada 10 min
  (~430 chamadas/dia com 1 par); expandir a lista de pares é decisão futura.

## Comandos

```bash
cd forex-daytrade
pip install -r requirements.txt
python -m pytest -q          # roda sem .env, sem rede
python main.py                # precisa de .env (ver .env.example)
```
