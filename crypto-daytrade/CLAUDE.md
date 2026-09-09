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
   `opened_at` e confere se o preço bateu no stop ou no alvo primeiro (`analysis/outcomes.py::check_outcome`
   — **checa o stop primeiro dentro de cada candle**, padrão conservador de backtest: se os dois seriam
   tocados no mesmo candle, assume que o stop bateu primeiro, não superestima acerto). Sinal aberto há mais de
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
Só resume sinais que o bot **já emitiu de verdade** — pra validar mudança de estratégia com amostra grande
antes de ir pra produção, ver "Backtest walk-forward" logo abaixo (módulo diferente, propósito diferente).

### Backtest walk-forward (`backtest/`, adicionado 2026-09-09)

Motivado pelo usuário reportando "muitas perdas" com a estratégia — mas os primeiros sinais reais (ver
"Status atual") eram uma amostra pequena (9) e correlacionada (quase todos "long", abertos numa janela de
8 minutos — provavelmente um único movimento de mercado, não 9 apostas independentes), então não dava pra
concluir nada com rigor. Esse módulo simula a estratégia (e variantes com filtro) candle a candle contra
meses de histórico REAL da Binance, reaproveitando a lógica de produção sem duplicar (`analysis/signals.py`
e `analysis/outcomes.py::check_outcome` são os mesmos usados por `main.py` — garante que o backtest testa
exatamente o que roda ao vivo, não uma reimplementação que pode divergir).

- **`data/binance_client.py::get_historical_klines()`** — candles de um intervalo de tempo arbitrário
  (paginado em blocos de 1000, o máximo por chamada), diferente de `get_klines()` que só pega "os N mais
  recentes" (isso é tudo que a execução ao vivo precisa).
- **`analysis/outcomes.py::check_outcome()`** — extraído de dentro de `main.py::resolve_open_signals` (era
  `_check_outcome`, função privada) pra virar compartilhado entre live e backtest.
- **`backtest/history.py`** — busca + cacheia candles em disco (`backtest/.cache/`, no `.gitignore` — é
  cache local, não versiona). Backtest roda a mesma janela várias vezes (uma por variante testada);
  buscar tudo de novo a cada vez seria lento à toa.
- **`backtest/filters.py`** — filtros de regime opcionais pra testar em cima do gatilho EMA/RSI já
  existente: `passes_adx_filter` (ADX(14) — abaixo de ~20-25 costuma indicar mercado de lado, onde
  cruzamento de EMA tende a ser ruído) e `passes_higher_timeframe_trend_filter` (exige que o timeframe
  maior, 1h, concorde com a direção do sinal de 15m). `adx()` mora em `analysis/indicators.py` (é um
  indicador puro, mesmo espírito de ema/rsi/atr), não em `backtest/` — só o *uso* dele como filtro é
  específico do backtest.
- **`backtest/engine.py::run_backtest()`** — processa **todos os símbolos no mesmo "relógio"**
  (timestamp por timestamp, não símbolo por símbolo do início ao fim) — necessário pro
  `Variant.max_concurrent_same_direction` fazer sentido: precisa saber quantas posições de OUTROS símbolos
  já estão abertas naquele instante exato, pra simular um limite de correlação entre pares (o padrão de
  "vários alts long ao mesmo tempo, o mercado reverte, todos batem stop juntos" observado em produção em
  2026-09-08 não é capturado testando símbolo por símbolo isoladamente).
- **`backtest/report.py`** — `analysis/performance.summarize()` continua sendo a fonte de wins/losses/
  win_rate; esse módulo só soma `r_multiple` (retorno em unidades de risco, calculado direto de
  entry/stop/close — não hardcoda `RISK_REWARD_RATIO`, funciona igual pra target_hit/stop_hit/expired),
  expectância (`expectancy_r`, média de R — >0 é expectativa positiva), profit factor e drawdown máximo em
  R (não é P&L em dinheiro, não há dimensionamento de posição aqui).
- **`backtest/run.py`** — CLI (`python -m backtest.run --days 90`). É o único arquivo do módulo que importa
  `config.py` (só pra reaproveitar `TOP_SYMBOLS_COUNT`/`TIMEFRAME`/`SIGNAL_EXPIRY_HOURS`, não duplicar) —
  por isso exige `.env`, mas `engine.py`/`filters.py`/`history.py` continuam sem essa dependência, testáveis
  sem credencial como o resto do projeto.

**Limitação conhecida**: `run.py` usa os pares de maior volume de **hoje** aplicados retroativamente ao
período inteiro do backtest (não reconstrói qual era o top-25 dia a dia no passado) — um símbolo listado há
pouco tempo (ex: apareceu com só ~4 dias de histórico num backtest de 60 dias) é claramente afetado por
isso. Não invalida a comparação entre variantes (todas rodam contra o mesmo conjunto de dados), mas o
número absoluto de expectância pode não se repetir exatamente se o conjunto de pares de maior volume mudar.

**Resultado do primeiro backtest real (60 dias, 25 pares, 2026-09-09)** — confirma com amostra grande
(4200+ trades) o que o usuário via ao vivo: baseline (estratégia de produção, sem filtro) deu
`expectancy_r ≈ -0.05`, profit factor `0.92` — **expectativa negativa confirmada**, não foi azar de amostra
pequena. Variante `+ tendência 1h` (só o filtro de timeframe maior, sem ADX) foi a única com expectativa
positiva: `expectancy_r ≈ +0.06`, profit factor `1.09`, drawdown máximo bem menor (101R vs 267R do
baseline) — reduz o volume de sinais em ~45%, mas melhora a qualidade do que sobra. Contra-intuitivo: ADX
sozinho **piorou** o resultado (`-0.10`) em vez de melhorar, e combinar ADX + 1h também ficou negativo — a
pesquisa genérica sobre ADX como filtro de tendência não se confirmou neste mercado/período específico;
quem decide o que vale é o backtest, não a heurística de "livro-texto". Decisão de que variante (se
alguma) vai pra produção ainda não foi tomada — pendente de decisão do usuário.

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

**O evento `schedule` do GitHub Actions não é confiável pra cron sub-horário (descoberto 2026-09-08)**:
mesmo com `*/10 * * * *` configurado corretamente (YAML válido, no branch default), medindo os runs reais
pela API (`GET /repos/MagroDaniel/TradeBot/actions/workflows/crypto_daytrade.yml/runs`) o evento `schedule`
só disparou 3x em ~11h de bot ativo, com ~3h de intervalo entre disparos — nunca a cada 10 min. Todos os
runs "extras" que apareciam no meio eram `workflow_dispatch` manual (o usuário clicando "Run workflow"),
não o cron. Isso é comportamento documentado/conhecido do GitHub: o evento `schedule` passa por uma fila de
agendamento compartilhada que não garante execução pontual pra frequências mais altas que ~1h, especialmente
em repositórios de baixa atividade — não é bug deste YAML nem falta de minutos (repo é público).

**Solução adotada**: um cron externo gratuito ([cron-job.org](https://cron-job.org)) chama
`POST /repos/MagroDaniel/TradeBot/actions/workflows/crypto_daytrade.yml/dispatches` a cada 10 min, com
`Authorization: Bearer <PAT>` (fine-grained personal access token, escopo só `Actions: read and write`, só
no repo `TradeBot`) e corpo `{"ref": "claude/daytrade-analysis-bot-u1uo4q"}` (branch default do repo).
Isso dispara o evento `workflow_dispatch`, que **não** passa pela fila do `schedule` e roda quase
instantaneamente (é por isso que os disparos manuais sempre funcionaram enquanto o cron nativo falhava). O
PAT fica cadastrado só no cron-job.org, nunca commitado no repo.

O bloco `schedule:` foi **removido** do workflow (não ficou como fallback) — decisão explícita do usuário
de manter uma única fonte de agendamento (`workflow_dispatch` via cron-job.org), evitando ambiguidade sobre
qual gatilho disparou cada run. Se o cron-job.org sair do ar, o bot simplesmente para de rodar
automaticamente até o serviço voltar ou até alguém disparar manualmente pela aba Actions — não há
fallback nativo do GitHub configurado.

**Binance bloqueia (HTTP 451) requisição vinda dos runners do GitHub Actions (descoberto 2026-09-08)**:
depois de corrigir o problema do `schedule` acima, o usuário reportou não ter recebido nenhuma mensagem no
Telegram o dia todo mesmo com o Actions rodando. Baixei os logs reais de todos os runs (inclusive o #1, o
primeiro que existiu) via `GET /repos/MagroDaniel/TradeBot/actions/runs/{id}/logs` — **toda** chamada às
rotas `/api/v3/*` da Binance falhava com `HTTPError: 451 Client Error` (`Unavailable For Legal Reasons`),
desde a primeira execução. `main.py` captura essa exceção por símbolo (`try/except` + `logger.error`) e
segue em frente, então o run terminava com `conclusion: success` mesmo sem conseguir buscar um único
candle — por isso `storage/signals.json` não mudou desde o commit `d9a20c1` (teste local do usuário, do
Brasil) apesar de 15 runs "bem-sucedidos". Causa: os runners `ubuntu-latest` do GitHub Actions rodam em
datacenter da Microsoft Azure nos **EUA**, e a Binance devolve 451 pra qualquer requisição de lá (mesma
restrição regulatória que já explica a Binance.US existir como exchange separada) — nada a ver com o bug
do `schedule` acima, que só afetava a frequência, não a origem da chamada.

**Solução adotada**: `binance-proxy/` (novo diretório na raiz do repo `TradeBot`, irmão de
`crypto-daytrade/`) — uma Vercel Function (`api/v3/[...path].js`) fixada na região `gru1` (São Paulo) via
`vercel.json`, que só repassa `GET /api/v3/*` pra `api.binance.com` e devolve a resposta como veio (sem
autenticação própria — a API de mercado da Binance usada aqui é pública e só leitura, não tem credencial
passando pelo proxy). `data/binance_client.py::BASE_URL` agora lê `BINANCE_API_BASE_URL` de
`os.getenv` (não de `config.py` — de propósito, pra não introduzir dependência de credencial do Telegram
nesse módulo e manter a suíte de testes rodando sem `.env`) com fallback pro endpoint oficial da Binance;
localmente (Brasil) essa variável fica vazia e continua batendo direto na Binance. O workflow
(`crypto_daytrade.yml`) passa `BINANCE_API_BASE_URL: ${{ secrets.CRYPTO_BINANCE_PROXY_URL }}` — enquanto
esse secret não existir, o Actions volta a tomar 451 (mesmo comportamento de antes, não piora nada). Ver
`binance-proxy/README.md` pros passos de deploy (import do repo na Vercel, root directory `binance-proxy`)
e cadastro do secret. **Resolvido em 2026-09-09**: proxy deployado (`trade-bot-one-chi.vercel.app`), secret
`CRYPTO_BINANCE_PROXY_URL` cadastrado, confirmado funcionando via logs reais do Actions (run #18 resolveu
9/9 sinais abertos, run #19 escaneou 25 pares sem nenhum erro). Nessa mesma investigação também apareceu
(e foi corrigido) um terceiro problema, sem relação com Binance/proxy: o grupo do Telegram tinha migrado
pra supergrupo, invalidando o `chat_id` antigo — `CRYPTO_TELEGRAM_CHAT_ID` foi atualizado pro novo ID que o
próprio erro 400 da API do Telegram devolveu (`migrate_to_chat_id`).

## Status atual

Reescrito do zero em 2026-09-08 (pivô de "listagens novas" pra "sinais técnicos"), testado de ponta a ponta
com dados e credenciais reais: `python main.py` rodado localmente, gerou **8 sinais reais de 25 pares
escaneados**, todos enviados com sucesso pro grupo do Telegram (formato confirmado pelo usuário — entrada/
stop/alvo/RSI, sem menção a alavancagem). `resolve_open_signals` ainda não foi exercitado de ponta a ponta
contra um sinal que realmente bateu stop/alvo/expirou nesse momento — isso já aconteceu depois, em produção
(ver "Automação" acima: run #18 do Actions resolveu os 9 sinais dessa leva inicial, 2 alvo / 7 stop).

GitHub Actions rodando de verdade a cada 10 min desde 2026-09-09 (cron externo via cron-job.org +
`workflow_dispatch`, proxy pro bloqueio 451 da Binance, `chat_id` do Telegram corrigido — ver "Automação").
75 testes automatizados passando, sem rede. Backtest walk-forward (`backtest/`) construído e rodado uma
vez contra 60 dias reais — ver "Backtest walk-forward" acima pro resultado. Nenhuma mudança em
`analysis/signals.py` foi aplicada ainda a partir desse resultado; produção continua com a estratégia
original (sem filtro de ADX/tendência 1h/correlação) até decisão do usuário.
