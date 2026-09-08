// Proxy read-only pra api.binance.com/api/v3/* — existe só por causa de um bloqueio
// geográfico: a Binance devolve HTTP 451 (Unavailable For Legal Reasons) pra requisições
// vindas de infraestrutura dos EUA, e é exatamente onde o GitHub Actions (ubuntu-latest) roda
// os runners do crypto-daytrade. Sem esse proxy, TODA chamada à API da Binance feita pelo
// workflow falha com 451 e o bot nunca gera/resolve sinal nem manda mensagem — descoberto em
// 2026-09-08 (ver CLAUDE.md do crypto-daytrade, seção "Automação").
//
// Fixado na região gru1 (São Paulo) via vercel.json — fora dos EUA, então a Binance atende
// normalmente. Quem chama bate em /api/v3/<endpoint> (ex: /api/v3/klines?symbol=...) igual
// bateria direto na Binance; o rewrite em vercel.json redireciona isso pra cá, colocando o
// pedaço de path capturado no query param `slug` (não existe rota de arquivo tipo
// api/v3/[...path].js aqui de propósito — testado e o catch-all "..." do Next.js não é
// honrado em projeto zero-config sem framework, só casa 1 segmento; rewrite explícito é a
// forma confiável de capturar path de profundidade variável nesse tipo de projeto).
export default async function handler(req, res) {
  if (req.method !== "GET") {
    res.status(405).json({ error: "method_not_allowed" });
    return;
  }

  const { slug, ...rest } = req.query;
  const path = Array.isArray(slug) ? slug.join("/") : slug || "";
  const qs = new URLSearchParams(rest).toString();
  const upstream = `https://api.binance.com/api/v3/${path}${qs ? `?${qs}` : ""}`;

  try {
    const upstreamRes = await fetch(upstream, {
      headers: {
        "User-Agent": "crypto-daytrade-proxy/1.0 (+https://github.com/MagroDaniel/TradeBot)",
      },
    });
    const body = await upstreamRes.text();
    res.status(upstreamRes.status);
    const contentType = upstreamRes.headers.get("content-type");
    if (contentType) res.setHeader("Content-Type", contentType);
    res.send(body);
  } catch (err) {
    res.status(502).json({ error: "proxy_failed", detail: String(err) });
  }
}
