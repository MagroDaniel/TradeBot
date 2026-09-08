# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é isto

Um bot que roda a cada 15-30 min (README, comentários e mensagens do Telegram — tudo em pt-BR) e checa
anúncios novos de listagem de criptomoeda na Binance, resume o risco que a própria Binance sinalizou no
anúncio (Seed Tag / Innovation Zone / Monitoring Tag) e o momentum de mercado (se já estiver operando), e
manda um alerta pelo Telegram. **Ele nunca compra nada sozinho** — só alerta; a decisão e a execução ficam
com o humano. Projeto irmão de `../sports-betting/`, mesma filosofia (análise/alerta, não execução).

## Decisões já tomadas (não reabrir sem motivo)

- **Só análise/alerta, sem execução automática** — decisão explícita do usuário ao criar o projeto (mesma
  filosofia do bot de apostas). Risco de perda financeira automática, inclusive em token golpe, foi motivo
  citado pra não automatizar a compra.
- **Não existe fórmula de "vai bombar"** — diferente do bot de apostas (EV = probabilidade do modelo vs.
  odd de mercado, um número objetivo), aqui não há edge matemático comparável. `analysis/scoring.py` se
  limita a resumir dois sinais objetivos (risco sinalizado pela Binance + momentum de mercado), nunca produz
  uma recomendação binária "compra"/"não compra". Não adicione uma pontuação de "provável sucesso" sem
  discutir com o usuário — foi uma escolha deliberada de manter honesto sobre o que dá pra saber de verdade.
- **Fonte de dados: só Binance por enquanto** — decisão explícita do usuário ("de onde puxar a lista de
  moedas novas"), CoinGecko/CoinMarketCap ficaram de fora do escopo inicial.
- **Sinal de segurança: tags de risco da própria Binance, não checagem on-chain** — o usuário pediu
  "segurança anti-golpe (liquidez travada, concentração de holders, contrato auditado)" como critério, mas
  a implementação inicial usa as tags que a Binance já aplica no anúncio (Seed Tag etc.) em vez de integrar
  uma API de segurança on-chain (ex: GoPlus) — mais simples, mais confiável pro escopo de "é arriscado
  segundo a própria exchange", e não depende de extrair endereço de contrato do anúncio (nem sempre
  disponível). Checagem on-chain mais profunda é um roadmap item, não implementada.
- **Telegram separado do bot de apostas** — bot e grupo próprios, não reaproveita credenciais.
- **Frequência: 15-30 min**, não 1x/dia — decisão explícita do usuário, já que listagem de cripto acontece
  a qualquer hora (diferente de futebol, que tem horário de jogo).

## Comandos

```bash
# Setup
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Roda uma checagem (pensado pra rodar via cron a cada 15-30 min, não continuamente)
python main.py

# Testes (sem chamadas de rede, sem precisar de credenciais)
pytest
```

As credenciais (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) são obrigatórias — `config.py` levanta
`RuntimeError` na importação se estiverem faltando, então `main.py` não pode ser importado sem um `.env`
válido. `data/binance_client.py`, `analysis/scoring.py`, `storage/seen_listings.py` e
`alerts/telegram_notifier.py` não têm essa dependência — a suíte de testes cobre todos esses mockando
`requests`, sem precisar de credenciais reais.

## Arquitetura

`main.py::main()` roda uma checagem por execução (não é um loop contínuo — a repetição vem do
agendamento externo via cron/GitHub Actions):

1. Busca os últimos anúncios da categoria "New Cryptocurrency Listing"
   (`BinanceClient.get_new_listing_announcements`).
2. Filtra os que ainda não foram vistos (`SeenListingsStore.seen_ids()`).
3. Pra cada anúncio novo: extrai o ticker do título (regex sobre o texto entre parênteses — ex: "Binance
   Will List MarsCoin (MARSCOIN)" → `MARSCOIN`; nem todo título tem esse padrão, ex: anúncios de futuros
   perpétuos não têm parênteses de ticker e ficam com `ticker=None`, o que já filtra naturalmente pra fora
   a maioria dos anúncios que não são listagem nova de spot), confere se o par `{ticker}USDT` já está
   `TRADING` na Binance, busca o ticker de 24h se estiver, e gera um `Assessment` (ver "Modelo de
   avaliação" abaixo).
4. Envia um alerta por anúncio novo pro Telegram.
5. Só marca como visto **depois** de tentar enviar todos — se o processo cair no meio, os que falharam
   continuam "não vistos" e são retentados na próxima execução (ver `main.py`, comentário no fim da função).

### Fonte de anúncios (`data/binance_client.py`)

`ANNOUNCEMENTS_URL` é o endpoint que o **próprio site da Binance usa internamente** pra listar
comunicados — **não é uma API oficialmente documentada/suportada**, pode mudar de formato ou parar de
funcionar sem aviso. `catalogId=48` corresponde a "New Cryptocurrency Listing" (confirmado manualmente
testando o retorno em 2026-09) — se o bot parar de achar anúncios novos, esse é o primeiro lugar a checar
(o catalogId pode ter mudado, ou o endpoint pode ter sido descontinuado).

Em contraste, `MARKET_BASE_URL` (`/api/v3/*`) **é** a API pública oficial de mercado da Binance,
documentada e estável — usada só pra `exchangeInfo` (checar se um par está `TRADING`) e `ticker/24hr`
(momentum). Nenhum dos dois grupos de endpoint exige chave de API.

### Modelo de avaliação (`analysis/scoring.py`)

`assess()` NUNCA produz uma recomendação binária — só resume dois sinais:
- `risk_tags`: quais das `RISK_TAGS` (`"Seed Tag"`, `"Innovation Zone"`, `"Monitoring Tag"`) aparecem no
  título do anúncio, case-insensitive. Ausência de tag não significa "seguro" — só que a Binance não
  aplicou aviso extra (ver docstring do módulo). `is_high_risk` é `bool(risk_tags)`.
- `price_change_percent` / `quote_volume`: vêm direto do `ticker/24hr` da Binance quando o par já está
  `TRADING`; `None` quando ainda não tem dado de mercado (anúncio saiu antes da moeda começar a operar).

Se algum dia adicionar um novo sinal (ex: segurança on-chain via GoPlus, hype social), estenda `Assessment`
como mais um campo descritivo em `summary()` — não transforme isso numa pontuação agregada de "compra"
sem decisão explícita do usuário (ver "Decisões já tomadas" acima).

### Armazenamento (`storage/seen_listings.py`)

JSON simples com uma lista de `article_id`s já vistos, limitada a 500 (`_MAX_IDS_KEPT`) pra não crescer pra
sempre — mesmo raciocínio de simplicidade do bot de apostas (`storage/picks_store.py` lá).

### Mensagens do Telegram (`alerts/telegram_notifier.py`)

Ícone 🚨 quando `assessment.is_high_risk`, senão 🆕. Toda mensagem termina com um disclaimer fixo
(`_DISCLAIMER`) deixando claro que não é previsão de alta e que bots profissionais costumam já ter
capturado o movimento antes do alerta chegar — não remova esse aviso sem decisão explícita do usuário, é
uma proteção deliberada dado o perfil de risco do domínio (bem mais arriscado que apostar contra uma odd
de mercado, que já tem o próprio disclaimer de EV no bot de apostas).

## Status atual

Scaffold inicial criado e testado com dados reais (2026-09-08): `get_new_listing_announcements` +
`find_trading_usdt_pair` + `get_24hr_ticker` + `assess()` rodados de ponta a ponta contra a API real da
Binance (achou o anúncio real da MarsCoin com "Seed Tag", casou com o par `MARSCOINUSDT` já operando, e
mostrou o momentum real de -15.6% em 24h). Suíte de testes (19 testes) passando, sem rede.

**Ainda não configurado**: bot/grupo do Telegram (precisa criar via @BotFather, separado do bot de
apostas), `.env` local, secrets do GitHub (`CRYPTO_TELEGRAM_BOT_TOKEN`/`CRYPTO_TELEGRAM_CHAT_ID` —
**prefixados com `CRYPTO_`** porque os secrets são por repositório, não por workflow, e
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` sem prefixo já existem no repo pro bot de apostas; olhar
`.github/workflows/crypto_daytrade.yml` pra ver o mapeamento exato secret→env var). O workflow em si já
existe (criado junto com o scaffold, ao contrário do bot de apostas onde eu só descobri um workflow
pré-existente). Nenhum teste de ponta a ponta com envio real pro Telegram ainda — só a parte de dados da
Binance foi validada com API real.

Pendência conhecida (decisão consciente, não bug): sem checagem de segurança on-chain (liquidez travada,
concentração de holders, contrato auditado) — usa só as tags de risco que a própria Binance aplica. Ver
"Decisões já tomadas" acima.
