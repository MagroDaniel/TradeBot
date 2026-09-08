# Bot de Análise — Apostas Esportivas (Futebol)

Bot que roda **1x por dia** e manda tudo pelo Telegram: primeiro o resultado
das apostas de ontem, depois as apostas de valor (+EV) identificadas para hoje.
Ele **não aposta sozinho** — só analisa e alerta. A decisão e execução ficam
com você.

## Como funciona

1. **Odds** — busca as odds do dia via [The Odds API](https://the-odds-api.com/)
   (free tier: 500 créditos/mês).
2. **Modelo** — estima a probabilidade real de cada resultado (vitória/empate/
   derrota, over/under 2.5 gols) usando um modelo de Poisson calibrado com
   resultados históricos do time (ataque/defesa relativos à média da liga).
3. **EV** — compara a probabilidade do modelo com a odd oferecida pelo mercado.
   Se `(prob_modelo × odd) - 1` passar do limiar configurado, vira um "pick".
4. **Stake** — sugere o tamanho da aposta via critério de Kelly fracionário
   (25% do Kelly cheio, por padrão), com um teto de segurança (3% da banca).
5. **Telegram** — no dia seguinte, confere o placar dos jogos apostados e manda
   o resultado; na sequência, manda os novos picks do dia.

## Por que só 1x por dia?

Cada chamada à The Odds API custa `regiões × mercados` créditos — mas já traz
**todos** os jogos futuros da liga de uma vez (não é por jogo). Com o free tier
(500 créditos/mês, ~16/dia), rodar várias vezes ao dia esgotaria o orçamento
rápido. Rodando 1x/dia (2 chamadas: placares + odds) o consumo fica bem abaixo
do limite, com folga para testes e ajustes no modelo.

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

### 3. Dados históricos (para calibrar o modelo)

Baixe o CSV da liga desejada em
[football-data.co.uk/data.php](https://www.football-data.co.uk/data.php)
(gratuito, sem precisar de chave de API). O arquivo já vem com as colunas
`HomeTeam`, `AwayTeam`, `FTHG`, `FTAG` que o `historical_loader.py` espera.

Salve o CSV em `data/historical/brasileirao.csv` (ou aponte
`HISTORICAL_DATA_PATH` no `.env` para outro caminho/liga). Dica: junte 2-3
temporadas no mesmo arquivo para o modelo ter mais dados — os nomes dos times
no CSV precisam bater com os nomes usados pela The Odds API para o mesmo
`SPORT_KEYS` (vale conferir e ajustar manualmente se necessário).

### 4. Rodar localmente

```bash
python main.py
```

### 5. Testes

```bash
pytest
```

Os testes cobrem o modelo de probabilidade, cálculo de EV e sizing de stake —
não fazem chamadas de rede, então rodam sem precisar de credenciais.

## Automação (GitHub Actions)

Já existe um workflow em `.github/workflows/daily_picks.yml` que roda o bot
todo dia às 08h (BRT) e commita de volta o histórico de picks (`storage/picks.json`)
para persistir entre execuções (os runners do GitHub Actions são efêmeros).

Para ativar:
1. Vá em **Settings → Secrets and variables → Actions** no repositório.
2. Adicione os secrets `ODDS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. Pronto — o workflow já roda sozinho no horário configurado (ou dispare
   manualmente pela aba Actions, via "Run workflow").

## Estrutura

```
sports-betting/
├── config.py                  # configuração via variáveis de ambiente
├── main.py                    # orquestra o job diário
├── data/
│   ├── odds_client.py         # cliente da The Odds API
│   └── historical_loader.py   # carrega resultados históricos (CSV)
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
- **Múltiplas ligas** — já dá pra configurar via `SPORT_KEYS`, mas cada liga
  nova consome mais créditos por execução; vale monitorar o orçamento.
- **Persistência mais robusta** — trocar o JSON por SQLite/Postgres se o
  histórico crescer muito.
- Projeto irmão de **daytrade** (mercado financeiro) compartilhando a mesma
  lógica de "probabilidade vs. preço de mercado" — planejado para depois.
