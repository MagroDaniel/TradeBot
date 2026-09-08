# Bot de Sinais Técnicos — Futuros/Spot Binance

Bot que roda **a cada 15-30 min** e escaneia os pares de maior volume na Binance em busca de
sinal técnico (cruzamento de médias móveis confirmado por RSI), mandando pro Telegram
**entrada, stop loss e alvo** — sem sugerir alavancagem. Ele **não opera nada sozinho** — só
analisa e alerta. A decisão e execução ficam com você.

## ⚠️ Antes de usar (ou vender) isto

Análise técnica **não tem edge matemático garantido** — diferente do bot de apostas
esportivas (`../sports-betting/`), que compara a probabilidade de um modelo contra a odd
oferecida pelo mercado (um número objetivo, EV). Aqui não existe equivalente. O que este bot
oferece é um método **transparente e honesto**: você sabe exatamente por que cada sinal saiu
(`Signal.reason`), e o histórico de acerto/erro é real, registrado em
`storage/signals.json` — nunca inventado ou filtrado pra esconder perda.

Se a ideia é oferecer isso pra outras pessoas (pago ou não), saiba que **isso tem implicação
regulatória no Brasil** — a CVM regula quem pode oferecer recomendação de operação financeira
de forma profissional (normalmente exige registro como analista de valores mobiliários).
Consulte um advogado/contador antes de cobrar de alguém por isso. Este projeto nunca vai
fabricar taxa de acerto, esconder perdas atrás de assinatura "VIP", ou sugerir alavancagem —
esses são exatamente os sinais de canal predatório que motivaram esse aviso.

## Como funciona

1. **Resolve sinais abertos** — pra cada sinal ainda em aberto, busca os candles desde que
   foi emitido e confere se o preço bateu no stop ou no alvo primeiro (ou expirou sem bater
   nenhum dos dois dentro de `SIGNAL_EXPIRY_HOURS`). Manda o resultado real pro Telegram.
2. **Escaneia por sinal novo** — pega os `TOP_SYMBOLS_COUNT` pares de maior volume (USDT,
   stablecoins excluídas), calcula EMA9, EMA21, RSI14 e ATR14 sobre os candles de
   `TIMEFRAME`, e gera um sinal quando a EMA rápida cruza a lenta **confirmado** por RSI numa
   faixa que não seja já sobrecomprada/sobrevendida.
3. **Telegram** — manda um alerta por sinal novo (entrada/stop/alvo/RSI/motivo) e depois,
   quando resolvido, o resultado real (alvo batido / stop batido / expirado).

## Estratégia (transparente, sem "caixa preta")

- **EMA9 cruza acima da EMA21** + RSI entre 30-65 → sinal de **compra (long)**.
- **EMA9 cruza abaixo da EMA21** + RSI entre 35-70 → sinal de **venda (short)**.
- **Stop loss**: 1,5× ATR14 de distância da entrada (proporcional à volatilidade recente do
  próprio par, não um valor fixo igual pra qualquer moeda).
- **Alvo**: 2× a distância do stop (relação risco:retorno de 1:2).

É uma estratégia clássica de "tendência + confirmação de momentum" — bem documentada,
replicável, mas **sem garantia de lucro**. Mercado lateral (sem tendência definida) tende a
gerar sinais falsos com qualquer estratégia baseada em cruzamento de médias, esta incluída.

## Setup

### 1. Instalar dependências

```bash
cd crypto-daytrade
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Credenciais

Copie `.env.example` para `.env` e preencha:

```bash
cp .env.example .env
```

- `TELEGRAM_BOT_TOKEN` — crie um bot **separado** do bot de apostas via
  [@BotFather](https://t.me/BotFather) no Telegram e copie o token.
- `TELEGRAM_CHAT_ID` — crie um grupo, adicione o bot, mande uma mensagem começando com `/`
  (ou desative o modo de privacidade do bot via `/setprivacy` no @BotFather) e acesse
  `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` pra descobrir o `chat.id`. **Grupo
  tem chat_id negativo** (ex: `-1001234567890`) — não esqueça o sinal de `-`. Se o grupo virar
  "supergrupo" automaticamente (o Telegram às vezes faz isso sozinho), o `chat_id` muda de
  novo — a resposta de erro do Telegram já traz o novo ID (`migrate_to_chat_id`).

### 3. Rodar localmente

```bash
python main.py
```

### 4. Testes

```bash
pytest
```

Os testes cobrem os indicadores técnicos, a geração de sinal, o resumo de performance e a
formatação das mensagens — não fazem chamadas de rede, então rodam sem precisar de
credenciais.

## Automação (GitHub Actions)

Workflow em `../.github/workflows/crypto_daytrade.yml` (raiz do repositório Git) — roda a
cada 15 minutos e commita `storage/signals.json` de volta a cada execução (histórico
persiste entre runs, já que os runners são efêmeros).

**Atenção**: os secrets do GitHub Actions são por repositório, não por workflow — como este
repo já tem `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` configurados pro bot de apostas, os
deste bot usam nomes prefixados: `CRYPTO_TELEGRAM_BOT_TOKEN` e `CRYPTO_TELEGRAM_CHAT_ID`.

Para ativar:
1. Vá em **Settings → Secrets and variables → Actions** no repositório.
2. Adicione os secrets `CRYPTO_TELEGRAM_BOT_TOKEN` e `CRYPTO_TELEGRAM_CHAT_ID`.
3. Em **Settings → Actions → General → Workflow permissions**, confirme "Read and write
   permissions".
4. Pronto — o workflow já roda sozinho a cada 15 min (ou dispare manualmente pela aba
   Actions, via "Run workflow").

## Estrutura

```
crypto-daytrade/
├── config.py                  # configuração via variáveis de ambiente
├── main.py                    # orquestra resolver + escanear
├── data/
│   └── binance_client.py      # top pares por volume + candles (klines)
├── analysis/
│   ├── indicators.py          # EMA, RSI, ATR (funções puras)
│   ├── signals.py             # decide entrada/stop/alvo a partir dos indicadores
│   └── performance.py         # resume o histórico real de acerto/erro
├── storage/
│   └── signals_store.py       # rastreia sinais emitidos e seus resultados
├── alerts/
│   └── telegram_notifier.py   # formatação e envio das mensagens
└── tests/
```

## Limitações conhecidas / roadmap

- **Só Binance, só EMA+RSI+ATR** — sem outros indicadores (MACD, Bollinger, volume profile
  etc.) nem outras exchanges por enquanto.
- **Sem backtest histórico** — a performance só é rastreada a partir de agora
  (`storage/signals.json` começa vazio); não há validação contra anos de dados passados
  antes do primeiro sinal real.
- **Mercado lateral gera sinal falso** — limitação conhecida de qualquer estratégia de
  cruzamento de médias, não é bug.
- Projeto irmão do bot de apostas esportivas (`../sports-betting/`), mesma filosofia — só
  análise e alerta, sem executar nada sozinho.
