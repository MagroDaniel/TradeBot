# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é isto

Um bot que roda 1x por dia (README, comentários e mensagens do Telegram — tudo em pt-BR) e analisa odds de
apostas de futebol, encontra apostas +EV ("de valor") usando um modelo de Poisson calibrado com resultados
históricos, e manda os picks pelo Telegram. **Ele nunca aposta sozinho** — só alerta; a decisão e a
execução ficam com o humano.

## Decisões já tomadas (não reabrir sem motivo)

São escolhas de produto deliberadas, não descuidos — reabrir a discussão exige um motivo declarado:

- **1x/dia, de manhã**, sem polling contínuo — motivado pelo orçamento do free tier da The Odds API (ver
  "Fronteira de acesso a dados" abaixo).
- **Somente análise/alerta, sem execução automática** — o bot nunca deve apostar sozinho.
- **Poisson simplificado (Maher 1982), não Dixon-Coles completo** — a correção para placares baixos é uma
  melhoria conhecida e propositalmente adiada (ver "Modelo" abaixo).
- **Dados históricos de calibração vêm de CSV** (não de uma API própria), mantidos separados do feed de
  odds ao vivo (The Odds API) — as duas fontes nunca devem se fundir num único cliente. **Atenção:** o
  football-data.co.uk (citado no README original) **não cobre o Brasileirão**, só ligas europeias — para
  o `SPORT_KEYS` padrão (`soccer_brazil_campeonato`) a fonte é o
  [adaoduque/Brasileirao_Dataset](https://github.com/adaoduque/Brasileirao_Dataset) no GitHub. O
  `historical_loader.py` detecta automaticamente qual dos dois formatos de coluna está no CSV.
- **Armazenamento em JSON simples**, pensado para ser trocado por SQLite/Postgres só se o volume de
  histórico exigir — não "conserte" isso preventivamente.

## Comandos

```bash
# Setup
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Roda o job diário (resolve os picks de ontem, depois envia os de hoje)
python main.py

# Testes (sem chamadas de rede, sem precisar de credenciais)
pytest
pytest tests/test_poisson_model.py            # um arquivo só
pytest tests/test_poisson_model.py::test_stronger_attacking_team_favored  # um teste só
```

As credenciais são variáveis de ambiente obrigatórias (`ODDS_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`), carregadas via `.env` (ver `.env.example`) através do `config.py`. O `config.py`
levanta `RuntimeError` na importação se elas estiverem faltando — ou seja, o `main.py` não pode ser
importado sem um `.env` válido, mas os módulos em `model/`, `analysis/`, `data/historical_loader.py`,
`storage/` e `backtest/` não têm essa dependência, por isso a suíte de testes cobre só esses.

## Arquitetura

O pipeline em `main.py::main()` roda duas fases em ordem fixa a cada execução, ambas usando a mesma
instância de `OddsAPIClient`:

1. **`resolve_yesterday()`** — carrega os picks salvos de ontem via `PicksStore`, busca os placares para
   os sport keys relevantes, marca cada pick como `"green"`/`"red"` recalculando o resultado a partir do
   placar bruto (ver `_pick_won`), grava os resultados de volta e envia o resumo pelo Telegram.
2. **`build_todays_picks()`** — recalibra um `PoissonModel` do zero a partir do CSV histórico a cada
   execução (não há modelo persistido/cacheado), busca as odds de hoje por sport key e avalia cada evento.

A avaliação por evento (`_evaluate_event`) é a lógica de decisão central e conecta os outros módulos:
`PoissonModel.match_probabilities()` → compara com `_best_odds_by_selection()` (melhor preço entre as casas
de apostas para cada uma das 5 seleções: vitória do mandante / empate / vitória do visitante / over 2.5 /
under 2.5) → `calculate_ev()` do `ev.py` → filtra por `config.EV_THRESHOLD` → `capped_stake()` do `kelly.py`
para o sizing → filtra stake `> 0` → gera um `Pick`.

Os resultados são enviados ao Telegram nesta ordem fixa (resultados de ontem, depois picks de hoje) — é uma
decisão de produto deliberada, não incidental; preserve essa ordem se mexer no `main()`.

### Modelo (`model/poisson_model.py`)

Abordagem simplificada de Maher (1982), precursora do Dixon-Coles (a correção completa de Dixon-Coles para
placares baixos está listada como não implementada no roadmap do README — não assuma que ela existe). Cada
time recebe uma força de ataque/defesa relativa às médias da liga, calculada separadamente a partir dos
jogos como mandante e como visitante e depois com a média entre os dois. Os gols esperados de uma partida
vêm de `média_liga × ataque_do_atacante × defesa_do_adversário`; as probabilidades da partida são a soma
dupla sobre uma grade de Poisson truncada (`max_goals`, padrão 8), então as probabilidades somam ~1.0 mas
não exatamente (ver a tolerância em `test_match_probabilities_sum_to_one`). Times não vistos na calibração
histórica levantam `KeyError` — quem chama (`main.py::_evaluate_event`) captura isso por evento e pula em
vez de derrubar a execução inteira, já que os nomes dos times na odds API e no CSV histórico precisam bater
exatamente (ver `data/team_aliases.py` abaixo).

**Ponderação temporal (`half_life_days`)**: a calibração pesa jogos recentes mais que antigos por
decaimento exponencial (peso cai pela metade a cada `half_life_days`; padrão 1095 = 3 anos, configurável via
`MODEL_HALF_LIFE_DAYS` no `.env`, `None`/`"none"` desativa). Existe porque times historicamente fortes mas
em fase ruim atualmente (ex: Corinthians, vários títulos entre 2005-2017) inflavam demais a força estimada
sem isso — mesmo com a ponderação, alguns EVs continuam artificialmente altos (>50%), porque o modelo ainda
não tem nenhum sinal de forma recente de curtíssimo prazo (últimos 5-10 jogos, lesões etc.); trate EVs muito
altos com desconfiança, não como edge real confirmado. `MatchResult.match_date` é opcional — sem data
(`None`) o jogo entra com peso 1.0, igual ao comportamento antes dessa mudança.

### Lógica financeira (`analysis/ev.py`, `analysis/kelly.py`)

Responsabilidades deliberadamente separadas: `ev.py` só compara a probabilidade do modelo com a odd de
mercado (`prob_modelo × odd - 1`); `kelly.py` só dimensiona o stake dado um edge (Kelly fracionário, padrão
25% do Kelly cheio, travado em `MAX_STAKE_FRACTION` da banca). Ambos são funções puras, sem I/O — mantenha
assim, é o que permite testá-los sem mocks.

### Fronteira de acesso a dados

`data/odds_client.py` e `data/historical_loader.py` são os únicos módulos que saem do processo (HTTP e CSV
no filesystem, respectivamente). O `OddsAPIClient` é um wrapper fino, sem cache — cada chamada custa
`regiões × mercados` créditos independente de quantos eventos voltam, por isso o bot foi desenhado para
rodar 1x/dia (ver "Por que só 1x por dia?" no README). Não adicione chamadas extras sem considerar o
orçamento de créditos do free tier (~16/dia). Os dados históricos vêm de CSV, com o formato de colunas
detectado automaticamente (`_COLUMN_ALIASES` em `historical_loader.py`): `HomeTeam`/`AwayTeam`/`FTHG`/`FTAG`
(football-data.co.uk, ligas europeias) ou `mandante`/`visitante`/`mandante_Placar`/`visitante_Placar`
(adaoduque/Brasileirao_Dataset, usado para o `SPORT_KEYS` padrão); linhas malformadas são silenciosamente
ignoradas, e um CSV com colunas de nenhum dos dois formatos levanta `ValueError`. A coluna de data
(`Date`/`data`, também autodetectada) alimenta a ponderação temporal do modelo — ver "Modelo" acima.

**Nomes de times (`data/team_aliases.py`)**: a Odds API e o CSV histórico usam nomenclaturas diferentes pro
mesmo time (ex: "Botafogo" vs. "Botafogo-RJ", "Vasco da Gama" vs. "Vasco"). `TEAM_ALIASES` mapeia Odds API →
CSV e é aplicado só na hora de consultar o modelo (`main.py::_evaluate_event`) — os nomes exibidos no
Telegram e salvos em `Pick` continuam sendo os originais da Odds API. Times genuinamente sem histórico no
CSV (ex: recém-promovidos à Série A) não têm solução por alias — continuam sendo pulados via `KeyError`, o
que é o comportamento correto.

### Armazenamento (`storage/picks_store.py`)

JSON simples indexado por data ISO, com listas de dataclasses `Pick` serializadas como valores. `Pick` é o
tipo de registro compartilhado que atravessa todo o pipeline (avaliação de odds → armazenamento →
resolução de resultado → formatação do Telegram → backtest). Ele acumula os estados "previsto" e
"resolvido" via os campos opcionais `result`/`profit_units`, em vez de ser dividido em tipos separados —
espere que essa dataclass seja lida e escrita bem além de `storage/`. O README deixa claro que isso é
propositalmente simples e deve ser trocado por SQLite/Postgres se o histórico crescer.

### Automação

**Atenção à raiz do repo**: `sports-betting/` é uma subpasta dentro do repositório Git `TradeBot` (o
remote é `MagroDaniel/TradeBot`) — não é a raiz. `.github/workflows/daily_picks.yml` fica na raiz do repo
(`TradeBot/.github/...`), não dentro de `sports-betting/.github/...`; procure lá se for mexer nele. O
workflow já existe e roda: cron diário (11h UTC = 08h BRT) + `workflow_dispatch` (disparo manual),
`working-directory: sports-betting`, instala dependências, roda `python main.py` com as 3 credenciais como
secrets, e commita+pusha `storage/picks.json` de volta (runners são efêmeros). Falta só os secrets serem
configurados no GitHub (Settings → Secrets and variables → Actions) — o workflow em si está pronto.

## Status atual

Já feito:

- `.env` criado e as 3 credenciais validadas com um teste real (`ODDS_API_KEY` retornou eventos de
  `soccer_brazil_campeonato`; Telegram confirmou o envio de uma mensagem de teste).
- Ambiente local pronto: `.venv/` criado, dependências de `requirements.txt` instaladas, `pytest` passando
  (26/26).
- CSV histórico baixado (`adaoduque/Brasileirao_Dataset`, 2003-2024, 8785 partidas) em
  `data/historical/brasileirao.csv`. README corrigido — football-data.co.uk não cobre o Brasileirão.
- Nomes de times conferidos contra a Odds API real e mapeados em `data/team_aliases.py` (6 aliases; 2 times
  — Mirassol, Remo — seguem sem histórico por serem recém-promovidos, não têm solução via alias).
- Ponderação temporal implementada no `PoissonModel` (`half_life_days`) depois de detectar EVs
  artificialmente altos (>100%) no primeiro run real — ver "Modelo" acima pra limitação remanescente.
- `python main.py` rodado de ponta a ponta com dados reais mais de uma vez (picks salvos em
  `storage/picks.json`, mensagens confirmadas no Telegram).

Ainda falta:

- Configurar os 3 secrets no GitHub (Settings → Secrets and variables → Actions: `ODDS_API_KEY`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) — o workflow (`TradeBot/.github/workflows/daily_picks.yml`, na
  raiz do repo) já existe e está pronto, só falta isso. **Próximo passo.**
- Considerado e adiado por decisão do usuário: um teto de EV (`EV_MAX_THRESHOLD`) como segunda camada de
  segurança contra os EVs ainda artificialmente altos em alguns picks — não implementado por ora.

## Projeto irmão (ainda não iniciado)

Um bot de "daytrade" (mercado financeiro) está planejado como um segundo projeto, compartilhando a mesma
lógica de fundo — probabilidade do modelo vs. preço de mercado, a mesma matemática do value betting daqui.
Ainda não existe código para ele.
