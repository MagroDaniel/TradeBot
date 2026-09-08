# TradeBot

Coleção de bots pessoais de análise de mercado — cada um foca num domínio diferente, mas
compartilham a mesma filosofia central: **analisam e alertam, nunca executam nada sozinhos.**
A decisão final e a execução (apostar, comprar, vender) são sempre manuais, de quem recebe o
alerta.

Nenhum dos dois projetos promete edge garantido. Onde existe uma comparação matemática
objetiva (bot de apostas: probabilidade do modelo vs. odd do mercado), ela é usada como
critério central. Onde não existe (bot de cripto: não há fórmula confiável pra "essa moeda
vai subir"), os bots se limitam a sinais transparentes e replicáveis — sem fabricar taxa de
acerto, sem esconder perda, sem prometer o que não conseguem sustentar.

## Projetos

### ⚽ [`sports-betting/`](sports-betting/) — Apostas esportivas (futebol)

Roda 1x por dia. Analisa odds de 9 competições (Brasileirão + 5 ligas europeias + 3 copas
UEFA) via [The Odds API](https://the-odds-api.com/), estima probabilidade real de cada
resultado com um modelo de Poisson calibrado por competição, e identifica apostas de
valor (+EV) — onde a odd oferecida paga mais do que a probabilidade real justificaria.
Sugere o tamanho da aposta via critério de Kelly fracionário. Manda tudo pro Telegram: o
resultado das apostas do dia anterior, depois os novos picks do dia.

Ver [`sports-betting/README.md`](sports-betting/README.md) e
[`sports-betting/CLAUDE.md`](sports-betting/CLAUDE.md) pra detalhes de setup e arquitetura.

### 🪙 [`crypto-daytrade/`](crypto-daytrade/) — Sinais técnicos (Binance)

Roda a cada 10 minutos, 24/7 (cripto não tem "horário de jogo"). Escaneia os pares de maior
volume na Binance em busca de sinal técnico (cruzamento de médias móveis EMA9/EMA21
confirmado por RSI14), calcula entrada/stop loss/alvo proporcionais à volatilidade recente
do par (ATR14), e manda pro Telegram — **nunca sugere alavancagem**. Rastreia o resultado
real de cada sinal (bateu alvo, bateu stop, ou expirou) e manda um relatório diário
completo, sem filtrar perdas.

Ver [`crypto-daytrade/README.md`](crypto-daytrade/README.md) e
[`crypto-daytrade/CLAUDE.md`](crypto-daytrade/CLAUDE.md) pra detalhes de setup e
arquitetura — inclui um aviso sobre a implicação regulatória (CVM) de oferecer sinais pra
terceiros no Brasil.

## Estrutura

```
TradeBot/
├── .github/workflows/          # automação (GitHub Actions) dos dois bots
├── sports-betting/             # bot de apostas esportivas
└── crypto-daytrade/            # bot de sinais técnicos de cripto
```

Cada projeto é independente — tem seu próprio `.env`, dependências (`requirements.txt`),
testes e bot/grupo do Telegram. Nenhuma credencial fica no código: tudo vem de variáveis de
ambiente, carregadas localmente via `.env` (nunca commitado — ver `.gitignore`) ou, em
produção, dos *secrets* do GitHub Actions do repositório.
