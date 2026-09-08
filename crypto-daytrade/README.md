# Bot de Análise — Novas Listagens na Binance

Bot que roda **a cada 15-30 min** e manda pro Telegram um alerta pra cada anúncio novo de
listagem de criptomoeda na Binance, com um resumo de risco (sinalizado pela própria Binance)
e momentum de mercado (se já estiver sendo negociada). Ele **não compra nada sozinho** — só
analisa e alerta. A decisão e execução ficam com você.

## Por que isso é diferente do bot de apostas esportivas

O bot irmão (`../sports-betting/`) compara a probabilidade de um modelo contra a odd
oferecida pelo mercado — um número objetivo (EV). **Não existe equivalente confiável pra
"essa moeda nova vai bombar".** Esse bot não tenta prever preço — ele só:

1. Avisa rápido quando um anúncio novo de listagem sai.
2. Resume o risco que a **própria Binance** já sinalizou (Seed Tag, Innovation Zone,
   Monitoring Tag — avisos de volatilidade/risco alto que a exchange aplica em listagens
   específicas).
3. Mostra o momentum de mercado (variação de preço, volume) nas primeiras horas, se a moeda
   já estiver sendo negociada.

Listagens novas são um dos espaços mais arriscados do mercado cripto — muito ligado a golpe
(rug pull) e a bots profissionais que capturam o movimento inicial antes de qualquer alerta
público chegar. Trate isso como uma ferramenta de triagem/vigilância, não como uma dica de
compra.

## Como funciona

1. **Anúncios** — busca os últimos anúncios da categoria "New Cryptocurrency Listing" no
   feed público que o próprio site da Binance usa (não é uma API oficialmente documentada —
   ver `data/binance_client.py`).
2. **Novidade** — compara contra os anúncios já vistos (`storage/seen_listings.json`) pra só
   alertar uma vez por anúncio.
3. **Momentum** — se a moeda já estiver com um par `{TICKER}USDT` operando na Binance, busca
   variação de preço e volume das últimas 24h.
4. **Risco** — procura no título do anúncio as tags de risco que a Binance aplica (Seed Tag,
   Innovation Zone, Monitoring Tag).
5. **Telegram** — manda um alerta por anúncio novo, com o resumo de risco + momentum e um
   aviso de que isso não é uma previsão de alta.

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
  tem chat_id negativo** (ex: `-1001234567890`) — não esqueça o sinal de `-`.

### 3. Rodar localmente

```bash
python main.py
```

### 4. Testes

```bash
pytest
```

Os testes cobrem o parsing de anúncios, a avaliação de risco/momentum e a formatação das
mensagens — não fazem chamadas de rede, então rodam sem precisar de credenciais.

## Automação (GitHub Actions)

Workflow em `../.github/workflows/crypto_daytrade.yml` (raiz do repositório Git, não dentro
de `crypto-daytrade/`) — roda a cada 15 minutos e não precisa commitar nada de volta (o
`storage/seen_listings.json` é reconstruído/atualizado a cada run e commitado de volta, igual
o bot de apostas faz com `picks.json`).

**Atenção**: os secrets do GitHub Actions são por repositório, não por workflow — como este
repo já tem `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` configurados pro bot de apostas, os
deste bot usam nomes **prefixados** pra não colidir: `CRYPTO_TELEGRAM_BOT_TOKEN` e
`CRYPTO_TELEGRAM_CHAT_ID`.

Para ativar:
1. Vá em **Settings → Secrets and variables → Actions** no repositório.
2. Adicione os secrets `CRYPTO_TELEGRAM_BOT_TOKEN` e `CRYPTO_TELEGRAM_CHAT_ID` (os do bot
   novo, separado do de apostas).
3. Em **Settings → Actions → General → Workflow permissions**, confirme "Read and write
   permissions" (já deve estar habilitado, o bot de apostas usa a mesma configuração).
4. Pronto — o workflow já roda sozinho a cada 15 min (ou dispare manualmente pela aba
   Actions, via "Run workflow").

## Estrutura

```
crypto-daytrade/
├── config.py                  # configuração via variáveis de ambiente
├── main.py                    # orquestra a checagem periódica
├── data/
│   └── binance_client.py      # anúncios de listagem + dados de mercado da Binance
├── analysis/
│   └── scoring.py             # resume risco (tags da Binance) + momentum
├── storage/
│   └── seen_listings.py       # rastreia anúncios já alertados
├── alerts/
│   └── telegram_notifier.py   # formatação e envio das mensagens
└── tests/
```

## Limitações conhecidas / roadmap

- **Só cobre a Binance** — a maior exchange, mas não a única. Outras exchanges (Coinbase,
  KuCoin, MEXC) ficam de fora por enquanto.
- **Feed de anúncios não é API oficial** — usa o mesmo endpoint que o site da Binance usa
  internamente (`catalogId=48`), pode mudar ou parar de funcionar sem aviso.
- **Sem checagem de segurança on-chain** — não verifica liquidez travada, concentração de
  holders ou contrato auditado (ex: via GoPlus Security API) — o sinal de risco de hoje vem
  só das tags que a própria Binance aplica. Cogitado como próximo passo.
- **Sem hype social** (Twitter/Telegram/Reddit) — mencionado como critério possível, não
  implementado ainda (custo de API e complexidade maiores).
- **Sem análise de fundamentos do projeto** (investidores, tokenomics) — também cogitado,
  não implementado.
- Projeto irmão do bot de apostas esportivas (`../sports-betting/`), compartilhando a mesma
  filosofia — "análise vs. preço/risco de mercado", só análise e alerta, sem execução
  automática.
