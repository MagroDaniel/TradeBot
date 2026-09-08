# Bot de Análise — Apostas Esportivas (Futebol)

Bot que roda **1x por dia** e manda tudo pelo Telegram: primeiro o resultado
das apostas de ontem, depois as apostas de valor (+EV) identificadas para hoje,
só entre os jogos que acontecem **hoje mesmo** (nada de mostrar jogo de sexta
numa mensagem de terça). Acompanha 9 competições — Brasileirão + 5 ligas
europeias + 3 copas europeias — pra sempre ter algo pra analisar, mesmo em
semanas de data-FIFA ou fora do fim de semana. Ele **não aposta sozinho** —
só analisa e alerta. A decisão e execução ficam com você.

## Como funciona

1. **Odds** — busca as odds do dia via [The Odds API](https://the-odds-api.com/)
   (free tier: 500 créditos/mês), uma competição de cada vez.
2. **Filtro do dia** — só entram jogos que começam hoje, em horário de
   Brasília — a Odds API devolve todos os jogos futuros da liga, não só os
   de hoje.
3. **Modelo** — estima a probabilidade real de cada resultado (vitória/empate/
   derrota, over/under 2.5 gols) usando um modelo de Poisson calibrado com
   resultados históricos do time (ataque/defesa relativos à média da liga),
   com um modelo calibrado separadamente **por competição** e ponderação
   temporal (jogos recentes pesam mais).
4. **EV** — compara a probabilidade do modelo com a odd oferecida pelo mercado.
   Se `(prob_modelo × odd) - 1` passar do limiar configurado, vira um "pick".
5. **Stake** — sugere o tamanho da aposta via critério de Kelly fracionário
   (25% do Kelly cheio, por padrão), com um teto de segurança (3% da banca).
6. **Notícias (opcional)** — pros jogos que geraram pick, checa via Claude
   (busca na web) se há lesão/suspensão/desfalque relevante e anexa um aviso
   curto na mensagem. **Não muda o cálculo do EV nem da probabilidade** — é
   só contexto pra você decidir na hora. Só ativa se `ANTHROPIC_API_KEY`
   estiver configurada; sem ela, o bot funciona normal, sem esse aviso.
7. **Telegram** — no dia seguinte, confere o placar dos jogos apostados e manda
   o resultado; na sequência, manda os novos picks do dia, agrupados por
   competição e por jogo.

## Competições acompanhadas

Configurável via `SPORT_KEYS` no `.env` — o padrão cobre:

| Competição | `sport_key` | Fonte do histórico |
|---|---|---|
| Brasileirão Série A | `soccer_brazil_campeonato` | [adaoduque/Brasileirao_Dataset](https://github.com/adaoduque/Brasileirao_Dataset) |
| Premier League | `soccer_epl` | [xgabora/Club-Football-Match-Data](https://github.com/xgabora/Club-Football-Match-Data) |
| La Liga | `soccer_spain_la_liga` | idem |
| Bundesliga | `soccer_germany_bundesliga` | idem |
| Serie A (Itália) | `soccer_italy_serie_a` | idem |
| Ligue 1 | `soccer_france_ligue_one` | idem |
| Champions League | `soccer_uefa_champs_league` | histórico combinado das 5 ligas acima |
| Europa League | `soccer_uefa_europa_league` | idem |
| Conference League | `soccer_uefa_europa_conference_league` | idem |

**Cada competição precisa do seu próprio CSV histórico** em
`data/historical/{sport_key}.csv` — competição sem CSV correspondente é
pulada (log de aviso), não derruba a execução das demais. As 3 copas
europeias compartilham o mesmo CSV combinado das 5 ligas domésticas — times
de ligas fora dessa lista (Porto, Ajax, Celtic etc.) não têm histórico e são
pulados, igual a qualquer time sem dado calibrado. Essa combinação é uma
simplificação (não normaliza a diferença de padrão de gols entre ligas
diferentes) — ver `CLAUDE.md` pra detalhes.

## Por que só 1x por dia?

Cada chamada à The Odds API custa `regiões × mercados` créditos — mas já traz
**todos** os jogos futuros da liga de uma vez (não é por jogo). Com 9
competições configuradas, uma execução completa consome ~18 créditos (2 por
competição). No free tier (500 créditos/mês) isso dá folga pra rodar 1x/dia
com sobra, mesmo com todas as competições ativas.

## Setup

### 1. Instalar dependências

```bash
cd sports-betting
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Credenciais

Copie `.env.example` para `.env` e preencha:

```bash
cp .env.example .env
```

- `ODDS_API_KEY` — sua chave da [The Odds API](https://the-odds-api.com/).
- `TELEGRAM_BOT_TOKEN` — crie um bot via [@BotFather](https://t.me/BotFather)
  no Telegram e copie o token.
- `TELEGRAM_CHAT_ID` — mande uma mensagem para o seu bot e acesse
  `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates` para descobrir o
  `chat.id` (funciona também para grupos).
- `ANTHROPIC_API_KEY` — **opcional**. Habilita a checagem de notícias (lesão/
  suspensão) via Claude com busca na web. Pegue a sua em
  [console.anthropic.com](https://console.anthropic.com/) — é a primeira
  dependência paga do projeto (custo pequeno por execução, cobrado por uso).
  Sem essa chave, o bot funciona normal, só sem esse aviso.

### 3. Dados históricos (para calibrar o modelo)

O `historical_loader.py` reconhece automaticamente o formato de duas fontes
gratuitas (nenhuma exige chave de API), pelas colunas do CSV:

- **Brasileirão** — o [football-data.co.uk](https://www.football-data.co.uk/data.php)
  **não cobre o Brasileirão** (só ligas europeias), então use o
  [adaoduque/Brasileirao_Dataset](https://github.com/adaoduque/Brasileirao_Dataset)
  (2003-2024). Baixe `campeonato-brasileiro-full.csv` — colunas `mandante`,
  `visitante`, `mandante_Placar`, `visitante_Placar`.
- **Ligas europeias e copas UEFA** — formato football-data.co.uk (`HomeTeam`,
  `AwayTeam`, `FTHG`, `FTAG`). O dataset consolidado
  [xgabora/Club-Football-Match-Data](https://github.com/xgabora/Club-Football-Match-Data)
  (`data/Matches.csv`, todas as ligas num arquivo só, filtrar por `Division`)
  é a fonte mais prática — cobre as 5 ligas domésticas de uma vez.

Salve cada CSV em `data/historical/{sport_key}.csv` (ex:
`data/historical/soccer_epl.csv`) — ou aponte `HISTORICAL_DATA_DIR` no `.env`
pra outro diretório com a mesma convenção de nomes. Dica: quanto mais
temporadas juntas, melhor — a ponderação temporal do modelo
(`MODEL_HALF_LIFE_DAYS`) já dá mais peso pros jogos recentes sozinha. Os
nomes dos times no CSV precisam bater com os nomes usados pela The Odds API
— divergências (ex: "Manchester United" vs. "Man United") vão em
`data/team_aliases.py`, aplicado automaticamente antes de consultar o
modelo.

### 4. Rodar localmente

```bash
python main.py
```

### 5. Testes

```bash
pytest
```

Os testes cobrem o modelo de probabilidade, cálculo de EV, sizing de stake,
carregamento de CSV, utilitários de data/hora e formatação das mensagens —
não fazem chamadas de rede, então rodam sem precisar de credenciais.

## Automação (GitHub Actions)

Já existe um workflow em `.github/workflows/daily_picks.yml` (na raiz do
repositório Git, não dentro de `sports-betting/`) que roda o bot todo dia às
07h (BRT) e commita de volta o histórico de picks (`storage/picks.json`)
para persistir entre execuções (os runners do GitHub Actions são efêmeros).

Para ativar:
1. Vá em **Settings → Secrets and variables → Actions** no repositório.
2. Adicione os secrets `ODDS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   (`ODDS_API_KEYS_EXTRA` e `ANTHROPIC_API_KEY` são opcionais — ver acima).
3. Em **Settings → Actions → General → Workflow permissions**, marque
   "Read and write permissions" (necessário pro commit automático de volta).
4. Pronto — o workflow já roda sozinho no horário configurado (ou dispare
   manualmente pela aba Actions, via "Run workflow").

## Estrutura

```
sports-betting/
├── config.py                  # configuração via variáveis de ambiente
├── main.py                    # orquestra o job diário
├── data/
│   ├── odds_client.py         # cliente da The Odds API
│   ├── historical_loader.py   # carrega resultados históricos (CSV)
│   ├── team_aliases.py        # nomes de times: Odds API -> CSV histórico
│   └── schedule.py            # utilitários de data/hora em BRT
├── model/
│   └── poisson_model.py       # probabilidade de resultado via Poisson
├── analysis/
│   ├── ev.py                  # probabilidade implícita / EV
│   └── kelly.py                # sizing de stake (Kelly fracionário)
├── storage/
│   └── picks_store.py         # persistência simples em JSON
├── alerts/
│   └── telegram_notifier.py   # formatação e envio das mensagens
├── backtest/
│   └── backtester.py          # ROI / taxa de acerto sobre o histórico
└── tests/
```

## Roadmap / próximas melhorias

- **Closing Line Value (CLV)** no backtest — métrica mais confiável do que
  ROI de curto prazo para saber se o modelo bate o mercado de forma consistente.
- **Dixon-Coles completo** (correção para placares baixos 0-0/1-0/0-1/1-1),
  hoje o modelo é uma versão simplificada (Maher, 1982).
- **Normalização entre ligas** para o modelo combinado das copas europeias —
  hoje mistura o histórico das 5 ligas domésticas sem ajustar pela diferença
  de padrão de gols entre elas.
- **Teto de EV** (`EV_MAX_THRESHOLD`) como segunda camada de segurança contra
  picks com edge artificialmente alto (cogitado, não implementado — revisão
  manual por enquanto).
- **Persistência mais robusta** — trocar o JSON por SQLite/Postgres se o
  histórico crescer muito.
- Projeto irmão **`../crypto-daytrade/`** — bot de análise de novas listagens de
  criptomoeda na Binance, mesma filosofia (só análise/alerta, sem executar
  nada sozinho).
