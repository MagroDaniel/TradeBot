# CLAUDE.md

App de day trade automático com painel web local (pt-BR). Sucessor do `../crypto-daytrade/`
(que continua rodando como bot de alertas no Telegram via GitHub Actions; não quebre ele).
Visão de uso em `README.md`; fases, decisões e pesquisa de estratégias em `PLANO.md`.

## Decisões já tomadas (não reabrir sem o usuário pedir)

- **Nunca alavancagem.** Spot só long; futuros long/short a 1x (margem = notional). Não
  adicione parâmetro de alavancagem.
- **Histórico real, nunca filtrado**: perdas aparecem no painel e no log como os ganhos.
- **Conta demo primeiro.** Hoje só existe `account="paper"`. Tudo no banco é separado por
  `account`, para paper, demo e live nunca se misturarem.
- **Estratégia nova só entra em uso depois de `python -m tradebot.research`** com R positivo
  em todas as fatias. Só `ema_cross` está validada (herdada do crypto-daytrade).
- **Sistema próprio**, sem copiar código GPL (Freqtrade/OctoBot); só ideias.
- **Vários robôs** (pedido do usuário): cada robô = 1 estratégia fixa + config + carteira demo
  própria (`bot_id` em wallets/positions/equity/events). Robôs não dividem saldo nem limite de
  posições, pra comparação justa. Kill switch e PARAR TUDO são globais.
- **Painel no navegador + processo em segundo plano** (não janela própria): fechar a tela não
  pode deixar posição sem stop. Ver `PLANO.md`.

## Comandos

```bash
pip install -r requirements.txt
python app.py                      # sobe motor + painel, abre o navegador
python -m tradebot.research        # backtest das estratégias com dados reais
pytest                             # sem rede, sem credenciais
```

`TRADEBOT_DATA_DIR` troca a pasta de dados (padrão `%APPDATA%\TradeBot` / `~/.tradebot`).
`TRADEBOT_SPOT_API_URL` / `TRADEBOT_FUTURES_API_URL` trocam os endpoints da Binance.

## Arquitetura (`tradebot/`)

- `models.py`: `Candle`, `Signal` + `ExitPlan`, `Position` (P&L e R calculados aqui).
- `strategies/`: cada estratégia tem `params` (`Param`, que vira formulário no painel),
  `timeframe`, `higher_timeframe`, `warmup`, `generate()` (só candles fechados) e
  `should_exit()` (opcional, avaliado no fechamento do candle). Registro em
  `strategies/__init__.py`.
  - `ema_cross` tem que continuar idêntica ao crypto-daytrade; o teste de paridade em
    `tests/test_strategies.py` garante isso.
  - A janela de candles importa: a EMA usa uma SMA como semente, então o motor e o backtest
    sempre passam exatamente `warmup` candles.
- `position.py::evaluate_bar`: a ÚNICA regra de saída, usada pelo backtest (por candle) e pelo
  motor (por preço).
  - Ordem: stop antes do alvo; trailing atualiza só depois e vale a partir do próximo candle;
    gap sai no preço de abertura.
- `risk.py`: kill switch (arquivo `HALT`), `check_entry` (limites), `active_protection`
  (perda diária / stops seguidos / drawdown), `symbol_in_cooldown`, `position_size`.
  - Só bloqueia ENTRADA. Sair nunca é bloqueado.
- `brokers.py`: `PaperBroker` (caixa no SQLite; preenchimento pelo livro real; recusa por
  slippage/saldo só na entrada).
  - Brokers futuros (Binance Demo, real) devem manter a mesma interface: `open`, `close`,
    `cash`, `equity`, `ensure_wallet`.
- `settings.py`: `AppSettings` (global: conta, `poll_seconds`, no kv `app_settings`) e
  `BotConfig` (por robô, na tabela `bots`). `BotConfig.from_dict` aceita o formato da versão 1
  (`strategy_params` aninhado por estratégia).
- `engine.py`: thread com `tick()` a cada `poll_seconds`; `Engine.bots: dict[int, Bot]`.
  - Por ciclo: preços 1x por mercado; candles com cache por ciclo (`_candle_cache`) compartilhado
    entre robôs (pede 502–1000 candles e fatia o `warmup` de cada estratégia).
  - Por robô/mercado: gerenciar posições → detectar candle fechado → `should_exit` → escanear.
  - Primeira execução sem robôs cria o robô 1 a partir de `kv['settings']`/`kv['engine_state']`
    da versão 1 (migração; `Store._migrate_v1` adiciona `bot_id` às tabelas antigas).
  - O primeiro candle depois de ligar é ignorado (não entra em sinal velho).
  - O estado (`stopped`/`running`/`paused`) de cada robô fica na tabela `bots` e é restaurado
    ao reabrir.
  - Erros repetidos são registrados 1x a cada 5 min.
- `store.py`: SQLite (WAL) com `kv`, `wallets`, `positions`, `events` (auditoria) e `equity`.
- `backtest.py`: multi-par no mesmo relógio, entrada na abertura seguinte, HTF só fechado,
  custos por lado.
  - `summarize`, `split_by_period` (consistência), `bootstrap_p_value` (blocos).
- `research.py`: CLI. Os dados vêm da API ou de `data.binance.vision`, com cache em
  `<dados>/cache`.
  - Universo fixo de pares líquidos, para evitar viés de sobrevivência.
  - Timestamps do arquivo spot desde 2025 vêm em microssegundos (`_to_ms`).
- `web/server.py`: FastAPI + Jinja + htmx. Rotas: `/` (visão geral), `/bots/{id}` (aba do
  robô), `/bots/{id}/settings`, `/bots/new`, `/settings` (global), comandos em
  `/api/bots/{id}/...`, `/api/emergency` e `/api/release-halt` globais.
  - Token por execução, trocado por cookie HttpOnly SameSite=Strict; tudo exige o cookie,
    menos `/health` e `/static`.
  - Comandos respondem 204 com `HX-Trigger` (`refresh` + `toast`).
  - JS embutido em `web/static/vendor/` (htmx 0BSD, lightweight-charts Apache-2.0, licenças
    ao lado): o app não depende de CDN.
- `app.py` (raiz): launcher. Porta livre em 127.0.0.1, `instance.json` garante uma instância
  só, abre o navegador.

## Fuso

Dia de negociação e limites diários em **UTC** (`risk.utc_day_start_ms`). Horários exibidos no
painel em BRT (UTC-3 fixo, mesma convenção do resto do repo).
