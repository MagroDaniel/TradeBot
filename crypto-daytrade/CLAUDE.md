# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é isto

Um bot que roda a cada 10 min (README, comentários e mensagens do Telegram — tudo em pt-BR) e escaneia
os pares de maior volume na Binance procurando sinal técnico (cruzamento de EMA9/EMA21 confirmado por
RSI14), mandando entrada/stop loss/alvo pro Telegram — nunca alavancagem. Ele **nunca opera nada sozinho**
— só alerta; a decisão e a execução ficam com o humano. Projeto irmão de `../sports-betting/`, mesma
filosofia (análise/alerta, não execução).

**Pivô de escopo (2026-09-08)**: este projeto começou como um bot de alerta de *novas listagens* na Binance
(ver commit `feat: scaffold bot de análise de novas listagens na Binance`). O usuário viu o resultado, não
gostou, e mostrou prints de canais de "sinais VIP" (entrada/stop/alvo/alavancagem, informação trancada
atrás de assinatura paga) como referência do que queria. O projeto foi **reescrito do zero** pra gerar
sinais técnicos de verdade — mas deliberadamente SEM copiar o padrão enganoso desses canais (ver "Decisões
já tomadas" abaixo). Se encontrar código ou histórico de commit mencionando "listagem"/"anúncio"/
`seen_listings`, é resquício do escopo antigo — não existe mais, não tente reviver.

## Decisões já tomadas (não reabrir sem motivo)

- **Nunca sugere alavancagem** — a decisão mais importante deste projeto. Canais de "sinal VIP" sempre
  recomendam um multiplicador (5x, 20x...); é o que mais quebra conta de quem segue o sinal, e é a marca
  registrada do padrão predatório que o usuário explicitamente pediu pra NÃO replicar. Não adicione um
  campo de alavancagem na mensagem ou no `SignalRecord` sem decisão explícita do usuário revisitando essa
  escolha.
- **Histórico de performance tem que ser real, nunca fabricado ou filtrado** — `storage/signals_store.py`
  registra TODO sinal emitido, e `analysis/performance.py` soma vitórias E derrotas. O usuário quer
  eventualmente oferecer/vender isso pra terceiros — nesse contexto, mostrar só os sinais que deram certo
  (como o canal de referência que ele mostrou) seria fabricar prova de desempenho. Não implemente nenhum
  filtro de exibição que esconda `stop_hit` do histórico.
- **Aviso regulatório**: vender recomendação de operação financeira no Brasil tem implicação da CVM
  (normalmente exige registro como analista de valores mobiliários). Isso não é um problema de código — é
  uma decisão de negócio do usuário, fora do escopo deste repositório — mas o README/CLAUDE.md deixam o
  aviso registrado porque veio explicitamente da intenção declarada de "vender pra outras pessoas".
- **Só análise/alerta, sem execução automática** — mesma filosofia do bot de apostas.
- **Estratégia clássica e documentada (EMA9/EMA21 + RSI14 + ATR14)**, não uma "caixa preta" — cada sinal
  carrega `reason` explicando exatamente por que saiu (ver "Modelo de sinal" abaixo). Escolhida por ser um
  método padrão, replicável e sem alegação de edge que não se pode sustentar.
- **Top pares por volume (~25), timeframe 15m** — decisão explícita do usuário. Stablecoins (USDC, USD1,
  FDUSD etc.) são filtradas na origem (`_STABLECOIN_BASES` em `binance_client.py`) porque têm volume alto
  mas preço travado em ~1.00, nunca geram cruzamento real — desperdiçariam uma chamada de klines por
  execução sem gerar sinal.
- **Telegram separado do bot de apostas** — bot e grupo próprios (secrets do GitHub prefixados `CRYPTO_`,
  ver "Automação" abaixo).

## Comandos

```bash
# Setup
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Roda uma checagem (pensado pra rodar via cron a cada 10 min, não continuamente)
python main.py

# Testes (sem chamadas de rede, sem precisar de credenciais)
pytest
```

As credenciais (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) são obrigatórias — `config.py` levanta
`RuntimeError` na importação se estiverem faltando, então `main.py` não pode ser importado sem um `.env`
válido. `data/binance_client.py`, `analysis/*`, `storage/signals_store.py` e
`alerts/telegram_notifier.py` não têm essa dependência — a suíte de testes cobre todos esses mockando
`requests`, sem precisar de credenciais reais.

## Arquitetura

`main.py::main()` roda uma checagem por execução (repetição vem do agendamento externo, não de um loop
interno):

1. **`send_daily_report_if_needed()`** — compara `today_brt()` (ver `data/schedule.py`) contra
   `store.get_last_report_date()`; se já bateu meia-noite BRT desde o último relatório, resume (via
   `analysis/performance.summarize`) todos os sinais cujo `closed_at` cai no dia anterior em BRT
   (`date_brt`) e manda pro Telegram. Só dispara 1x/dia mesmo rodando a cada 10 min — a checagem de data é
   o que evita repetir. Se o envio falhar, **não** marca `last_report_date` como enviado — tenta de novo na
   próxima execução (mesmo padrão de "só marca sucesso depois de confirmar" do resto do projeto).
2. **`resolve_open_signals()`** — pra cada sinal com `status="open"` em `SignalsStore`, busca candles desde
   `opened_at` e confere se o preço bateu no stop ou no alvo primeiro (`_check_outcome` — **checa o stop
   primeiro dentro de cada candle**, padrão conservador de backtest: se os dois seriam tocados no mesmo
   candle, assume que o stop bateu primeiro, não superestima acerto). Sinal aberto há mais de
   `SIGNAL_EXPIRY_HOURS` sem bater nenhum dos dois vira `"expired"`. Resultado real vai pro Telegram
   (`notifier.send_result`) e é persistido (`store.update`).
3. **`scan_for_new_signals()`** — pra cada um dos `TOP_SYMBOLS_COUNT` pares de maior volume que **não**
   já tem sinal aberto (`store.has_open_signal_for` — não empilha sinal novo em cima de aberto pro mesmo
   par), busca candles e chama `generate_signal()`. Se gerar sinal, manda pro Telegram e persiste.

Ordem (relatório → resolver → escanear) é deliberada — mesmo raciocínio do bot de apostas (resultado de
ontem antes dos picks de hoje): fecha o que já aconteceu antes de gerar coisa nova.

### Indicadores (`analysis/indicators.py`)

Funções puras, sem I/O — mesmo espírito de `analysis/ev.py`/`kelly.py` do bot de apostas. `ema()` usa SMA
como semente pros primeiros `period` valores (prática padrão). `rsi()` é o RSI de Wilder (suavização
exponencial das médias de ganho/perda, não SMA simples). `atr()` também usa suavização de Wilder. Todas
retornam listas alinhadas ao fim: o último elemento de qualquer uma dessas séries sempre corresponde ao
candle mais recente do input, mesmo que os arrays tenham tamanhos diferentes entre si (por causa dos
diferentes "aquecimentos" de cada período) — é assim que `signals.py` consegue comparar `[-1]`/`[-2]` de
séries de tamanhos diferentes sem alinhar manualmente.

### Modelo de sinal (`analysis/signals.py`)

`generate_signal()` retorna `None` na maioria das chamadas — sinal é evento raro por design, não um
palpite forçado a cada execução. Dispara quando:
- **Long**: EMA9 cruza de baixo pra cima da EMA21 **e** RSI14 no candle do cruzamento está entre 30-65
  (`LONG_RSI_RANGE`) — filtro que evita comprar já sobrecomprado mesmo com o cruzamento "a favor".
- **Short**: cruzamento inverso, RSI entre 35-70 (`SHORT_RSI_RANGE`).

Stop = `entry ∓ ATR_STOP_MULTIPLIER(1.5) × ATR14`; alvo = `entry ± RISK_REWARD_RATIO(2.0) × risco`. Os
testes (`tests/test_signals.py`) usam fixtures de preço sintético **validadas empiricamente** (uma sequência
de queda leve seguida de alta/queda calibrada pra cruzar as médias com o RSI dentro da faixa esperada) —
se for ajustar `LONG_RSI_RANGE`/`SHORT_RSI_RANGE` ou os períodos de EMA, terá que recalibrar essas
fixtures também (rodar o sinal contra a sequência sintética e conferir se ainda dispara — os valores atuais
não são arbitrários, foram encontrados por tentativa empírica, documentado no processo do commit).

### Fonte de dados (`data/binance_client.py`)

**Só usa `/api/v3/*`, a API pública oficial de mercado da Binance** (documentada, estável, sem chave) —
diferente do projeto antigo de listagens, que dependia de um endpoint não-oficial do site. Isso é uma
melhoria de robustez do pivô, não só uma coincidência.
- `get_top_symbols_by_volume()` — uma chamada só a `/ticker/24hr` sem `symbol` (devolve todos os pares),
  filtra por sufixo do par de cotação e exclui stablecoins, ordena por `quoteVolume`.
- `get_klines()` — candles OHLCV, mais antigo primeiro (ordem nativa da Binance, não invertida).

### Relatório diário e fuso horário (`data/schedule.py`)

Mesmo módulo/lógica do bot de apostas (`../sports-betting/data/schedule.py`) — BRT como offset fixo UTC-3,
sem `zoneinfo`/`pytz`. Cripto não tem "fechamento de pregão" como bolsa de valores, mas o usuário pediu um
relatório de fim de dia mesmo assim — meia-noite BRT foi escolhida como corte por ser a referência natural
pro público do bot (mesmo raciocínio do resto do projeto: BRT em vez do fuso do runner do GitHub Actions,
que roda em UTC).

### Armazenamento (`storage/signals_store.py`)

JSON simples (`SignalRecord` — symbol, direction, entry, stop_loss, target, rsi_value, reason, opened_at,
status, closed_at, close_price) igual em espírito ao `Pick`/`picks_store.py` do bot de apostas: um
registro que acumula estado "aberto" → "resolvido" via campos opcionais, em vez de tipos separados.
`update()` casa registros por `(symbol, opened_at)` — chave natural já que um símbolo pode ter vários
sinais ao longo do tempo (um por vez, já que `has_open_signal_for` impede sobreposição).

### Performance (`analysis/performance.py`)

Espelha `backtest/backtester.py` do bot de apostas. `win_rate` só considera `wins + losses` no denominador
— sinais `expired` não contam a favor nem contra (nem ganharam nem perderam, ficaram sem definição dentro
do prazo). **Nunca filtre `stop_hit` do que entra em `summarize()`** — ver "Decisões já tomadas" acima.

### Mensagens do Telegram (`alerts/telegram_notifier.py`)

`send_signal_alert` mostra entrada/stop/alvo/RSI/motivo + disclaimer fixo (nunca alavancagem, análise
técnica não é garantia). `send_result` usa ✅/❌/⌛ conforme `status`. Nenhum dos dois textos deve ser
editado pra remover o disclaimer ou pra "vender" o sinal com linguagem de certeza — ver "Decisões já
tomadas" acima.

### Automação

`.github/workflows/crypto_daytrade.yml` (raiz do repo `TradeBot`) — cron a cada 10 min +
`workflow_dispatch`. Secrets **prefixados `CRYPTO_`** (`CRYPTO_TELEGRAM_BOT_TOKEN`,
`CRYPTO_TELEGRAM_CHAT_ID`) porque secrets do GitHub Actions são por repositório, não por workflow, e os
nomes sem prefixo já pertencem ao bot de apostas no mesmo repo. Commita `storage/signals.json` de volta a
cada run (runners são efêmeros).

**Frequência e minutos do GitHub Actions**: rodava `*/15 * * * *` originalmente — 96 execuções/dia estoura
o free tier de 2.000 min/mês de repositório privado sozinho, só pelo arredondamento de minutos do GitHub
(cada run conta como no mínimo 1 min, mesmo rápido). Cogitado reduzir frequência, mas o usuário decidiu
tornar o repositório `TradeBot` **público** em vez disso (repositório público tem minutos ilimitados) —
antes disso, auditei todo o histórico do Git (`git log --all -p`) atrás de credencial commitada por engano
e não achei nada (nem `.env`, nem token, nem chave de API). Cron final: `*/10 * * * *`. Se o repo algum dia
voltar a ser privado, reconsidere a frequência antes de reativar o workflow como está.

## Status atual

Reescrito do zero em 2026-09-08 (pivô de "listagens novas" pra "sinais técnicos"), testado de ponta a ponta
com dados e credenciais reais: `python main.py` rodado localmente, gerou **8 sinais reais de 25 pares
escaneados**, todos enviados com sucesso pro grupo do Telegram (formato confirmado pelo usuário — entrada/
stop/alvo/RSI, sem menção a alavancagem). `resolve_open_signals` ainda não foi exercitado de ponta a ponta
contra um sinal que realmente bateu stop/alvo/expirou (só roda quando existe sinal `"open"` no
`storage/signals.json` — os 8 gerados nesse run ainda estavam abertos). 36 testes automatizados passando,
sem rede.

**Ainda pendente**: GitHub Actions (secrets `CRYPTO_TELEGRAM_BOT_TOKEN`/`CRYPTO_TELEGRAM_CHAT_ID`) — o
workflow já existe (`crypto_daytrade.yml`), só falta configurar os secrets e rodar uma vez lá pra confirmar
o pipeline completo (igual foi feito no bot de apostas).
