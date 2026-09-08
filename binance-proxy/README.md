# binance-proxy

Proxy read-only e sem estado pra `https://api.binance.com/api/v3/*`, fixado na região **gru1**
(São Paulo) da Vercel.

## Por que isso existe

O `crypto-daytrade` (projeto irmão nesse mesmo repositório) roda via GitHub Actions, cujos
runners (`ubuntu-latest`) ficam em datacenters da Microsoft Azure nos **EUA**. A Binance devolve
`HTTP 451 Unavailable For Legal Reasons` pra qualquer requisição vinda de infraestrutura dos
EUA — então toda chamada à API de mercado feita pelo workflow falhava, silenciosamente (o bot
capturava a exceção e seguia em frente), e nenhum sinal era gerado/resolvido nem mensagem
mandada pro Telegram. Descoberto em 2026-09-08 (ver `crypto-daytrade/CLAUDE.md`, seção
"Automação").

Esse proxy só repassa a chamada pra `api.binance.com` a partir de uma região fora dos EUA. Só
existe pra contornar o bloqueio geográfico — não adiciona autenticação, cache, nem lógica
própria. A API de mercado da Binance (`/api/v3/*`) é pública e só leitura (ticker, klines);
não tem chave de API nem segredo passando por aqui, então não tem credencial pra vazar mesmo
que a URL do proxy seja descoberta por terceiros (o único risco de deixar a URL pública é
alguém consumir a cota de execuções da Vercel, não vazamento de dado).

**Detalhe de implementação**: quem chama bate em `/api/v3/<endpoint>` normalmente (ex:
`/api/v3/klines?symbol=BTCUSDT`), igual bateria direto na Binance. Por baixo, um `rewrite` em
`vercel.json` redireciona isso pra uma function fixa (`api/proxy.js`) — **não** existe um
arquivo `api/v3/[...path].js` de propósito: testamos e o catch-all "`...`" do Next.js não é
honrado em projeto zero-config sem framework (preset "Other"), só casa exatamente 1 segmento de
path (`/api/v3/ping` funcionava, `/api/v3/ticker/price` dava 404 puro do roteador da Vercel,
antes mesmo de chegar na function). O `rewrite` explícito é a forma confiável de capturar path
de profundidade variável nesse tipo de projeto.

## Deploy (uma vez só)

1. Crie conta em https://vercel.com (dá pra logar direto com a conta do GitHub).
2. **Add New** → **Project** → **Import** o repositório `MagroDaniel/TradeBot`.
3. Em **Root Directory**, selecione `binance-proxy` (não a raiz do repo).
4. Framework preset: **Other** (não é Next.js, é só uma function solta).
5. Deploy. A URL final fica algo como `https://binance-proxy-xxxx.vercel.app`.
6. Cadastre essa URL + `/api/v3` como secret `CRYPTO_BINANCE_PROXY_URL` no repositório
   `TradeBot` (Settings → Secrets and variables → Actions) — ex:
   `https://binance-proxy-xxxx.vercel.app/api/v3`. O workflow do crypto-daytrade já está
   preparado pra usar essa variável (`BINANCE_API_BASE_URL`) quando ela existir.

## Teste manual

```
curl https://SEU-PROJETO.vercel.app/api/v3/ticker/price?symbol=BTCUSDT
```

Deve devolver o mesmo JSON que `https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT`
devolve.
