# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é isto

Um bot que roda 1x por dia (README, comentários e mensagens do Telegram — tudo em pt-BR) e analisa odds de
apostas de futebol em 9 competições (Brasileirão + 5 ligas europeias + 3 copas UEFA), encontra apostas +EV
("de valor") só entre os jogos que acontecem **hoje** (em horário de Brasília) usando um modelo de Poisson
calibrado por competição, e manda os picks pelo Telegram. **Ele nunca aposta sozinho** — só alerta; a
decisão e a execução ficam com o humano.

## Decisões já tomadas (não reabrir sem motivo)

São escolhas de produto deliberadas, não descuidos — reabrir a discussão exige um motivo declarado:

- **1x/dia, às 7h BRT**, sem polling contínuo — motivado pelo orçamento do free tier da The Odds API (ver
  "Fronteira de acesso a dados" abaixo). Mesmo com 9 competições + mercados adicionais por evento, uma
  execução completa fica bem abaixo do limite mensal.
- **Somente análise/alerta, sem execução automática** — o bot nunca deve apostar sozinho.
- **Só jogos de hoje** (`data/schedule.py::is_same_day_brt`) — a Odds API devolve todos os jogos futuros da
  liga numa chamada só; sem esse filtro o bot mostrava jogos de dias futuros como se fossem de hoje (bug
  reportado pelo usuário, corrigido nesta sessão).
- **Um modelo calibrado por competição**, nunca um modelo só pra várias ligas — médias de gols e pools de
  times são incompatíveis entre ligas (ver "Modelo" e "Fronteira de acesso a dados" abaixo).
- **Poisson simplificado (Maher 1982), não Dixon-Coles completo** — a correção para placares baixos é uma
  melhoria conhecida e propositalmente adiada (ver "Modelo" abaixo).
- **Dados históricos de calibração vêm de CSV** (não de uma API própria), um por competição, mantidos
  separados do feed de odds ao vivo (The Odds API) — as duas fontes nunca devem se fundir num único cliente.
- **Armazenamento em JSON simples**, pensado para ser trocado por SQLite/Postgres só se o volume de
  histórico exigir — não "conserte" isso preventivamente.
- **Bilhete de múltipla sugerido prioriza probabilidade, não EV** (`analysis/multiple.py`) — as pernas são
  as de maior `model_probability` do dia, mesmo que não sejam picks +EV, e o bilhete pode ter EV combinado
  negativo. Decisão explícita do usuário (opção recomendada apresentada) depois de eu levantar a alternativa
  de combinar só picks já +EV — que na prática teria pernas insuficientes na maioria dos dias pra montar um
  bilhete com odd relevante (o bot gera poucos picks +EV por dia). Puramente informativo, como a checagem de
  notícias: não vira `Pick`, não é salvo em `storage/`, não entra em sizing de stake.

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
`data/schedule.py`, `data/team_aliases.py`, `data/odds_client.py`, `data/news_check.py`,
`alerts/telegram_notifier.py`, `storage/` e `backtest/` não têm essa dependência, por isso a suíte de testes
cobre todos esses (mockando `requests`/`anthropic` nos módulos com I/O de rede, sem precisar de credenciais
reais). `ANTHROPIC_API_KEY` e `ODDS_API_KEYS_EXTRA` são opcionais — ver "Checagem de notícias" e "Fronteira
de acesso a dados" abaixo.

**`TELEGRAM_CHAT_ID` de grupo é negativo** (ex: `-5374137733`) — diferente de chat pessoal (positivo). Erro
comum: copiar o ID do JSON do `getUpdates` sem o sinal de `-`. Se o bot foi movido pra um grupo e parou de
mandar mensagem, esse é o primeiro lugar a checar.

## Arquitetura

O pipeline em `main.py::main()` roda duas fases em ordem fixa a cada execução, ambas usando a mesma
instância de `OddsAPIClient`:

1. **`resolve_yesterday()`** — carrega os picks salvos de ontem (data calculada em BRT, ver
   `data/schedule.py::today_brt`) via `PicksStore`, busca os placares para os sport keys relevantes, marca
   cada pick como `"green"`/`"red"` recalculando o resultado a partir do placar bruto (ver `_pick_won`),
   grava os resultados de volta e envia o resumo pelo Telegram.
2. **`_load_models()`** — calibra um `PoissonModel` por competição em `SPORT_KEYS`, a partir de
   `HISTORICAL_DATA_DIR/{sport_key}.csv`. Competição sem CSV correspondente é pulada (log de aviso), não
   derruba a execução das demais — não há modelo persistido/cacheado entre execuções.
3. **`build_todays_picks()`** — para cada competição com modelo calibrado, busca as odds via
   `OddsAPIClient.get_upcoming_odds`, filtra só os jogos de **hoje em BRT**
   (`is_same_day_brt`), busca mercados adicionais por evento (`_with_additional_markets`, ver
   "Fronteira de acesso a dados") e avalia cada evento, retornando `(picks, games_today, multiple)` — o
   terceiro item é o bilhete de múltipla sugerido (ver "Bilhete de múltipla" abaixo).
4. **`_check_news()`** — opcional (ver "Checagem de notícias" abaixo): checa lesão/suspensão pros jogos que
   geraram pick, um por partida.

A avaliação por evento é dividida em duas etapas (`main.py::SelectionCandidate` é o tipo intermediário
compartilhado entre elas):
`_selection_candidates()` chama `PoissonModel.match_probabilities()` → compara com
`_best_odds_by_selection()` (melhor preço entre as casas de apostas para cada uma das 10 seleções: vitória
do mandante / empate / vitória do visitante / over 2.5 / under 2.5 / ambas marcam / ambas não marcam / dupla
chance ×3) → `calculate_ev()` do `ev.py`, sem aplicar nenhum filtro ainda. A partir dessa lista de
candidatas, `_picks_from_candidates()` filtra por `config.EV_THRESHOLD` → `capped_stake()` do `kelly.py`
para o sizing → filtra stake `> 0` → gera um `Pick` (é a lógica de decisão central do bot, sem mudança de
comportamento desde antes do bilhete de múltipla existir); `_best_leg_for_multiple()` pega da mesma lista a
seleção de **maior `model_probability`** do evento (ignorando EV) pra alimentar o bilhete de múltipla — ver
abaixo. `_best_odds_by_selection` devolve `(odd, casa)` por seleção, não só a odd — o `title` da casa (ex:
"Bet365") vem junto no `Pick.bookmaker` e aparece na mensagem do Telegram entre parênteses ao lado da odd,
já que casas diferentes pagam preços diferentes pra mesma seleção. Campo opcional (`None` em picks salvos
antes dele existir, carregados via `Pick(**p)` — o default cobre isso sem migração de dado).

Os resultados são enviados ao Telegram nesta ordem fixa (resultados de ontem, depois picks de hoje) — é uma
decisão de produto deliberada, não incidental; preserve essa ordem se mexer no `main()`.

### Bilhete de múltipla (`analysis/multiple.py`)

Seção opcional (`config.MULTIPLE_LEGS`, padrão 4, `0` desativa) na mesma mensagem diária de picks — **não**
uma mensagem separada. Diferente do resto do pipeline, prioriza `model_probability` em vez de EV: pra cada
jogo de hoje, `main.py::_best_leg_for_multiple` pega a seleção de maior probabilidade (mesmo sem ser pick
+EV); `build_multiple()` pega as `MULTIPLE_LEGS` pernas de maior probabilidade entre todos os jogos do dia
(uma por jogo — nunca duas seleções do mesmo jogo, o que violaria a independência assumida no produto de
odds/probabilidades) e multiplica odds e probabilidades. Retorna `None` (a seção some da mensagem) se não
houver jogos suficientes hoje pra preencher `MULTIPLE_LEGS` — não sugere bilhete "incompleto".

Isso foi uma decisão explícita do usuário depois de eu apresentar a alternativa de combinar só picks já
+EV: na prática o bot gera poucos picks +EV por dia (às vezes 0), então quase nunca haveria pernas
suficientes pra um bilhete com odd relevante. **Puramente informativo, como a checagem de notícias**: não
vira `Pick`, não é salvo em `storage/`, não entra em `resolve_yesterday` (não é conferido/resolvido depois)
nem em nenhum sizing de stake — a mensagem mostra o EV combinado só como contexto (`combined_ev`, pode e
costuma ser negativo, já que a casa cobra margem em cada perna e o produto dessas margens cresce rápido) e
avisa isso explicitamente (`_MULTIPLE_EXPLAINER` em `alerts/telegram_notifier.py`). Aparece mesmo em dias
sem nenhum pick +EV, desde que haja jogos suficientes — é uma feature independente do funil de EV, não uma
extensão dele.

### Modelo (`model/poisson_model.py`)

Abordagem simplificada de Maher (1982), precursora do Dixon-Coles (a correção completa de Dixon-Coles para
placares baixos está listada como não implementada no roadmap do README — não assuma que ela existe). Cada
time recebe uma força de ataque/defesa relativa às médias da liga, calculada separadamente a partir dos
jogos como mandante e como visitante e depois com a média entre os dois. Os gols esperados de uma partida
vêm de `média_liga × ataque_do_atacante × defesa_do_adversário`; `match_probabilities()` percorre uma grade
de Poisson truncada (`max_goals`, padrão 8) uma única vez e deriva **todos** os mercados dela (1X2,
over/under 2.5, BTTS, dupla chance) — probabilidades 1X2 somam ~1.0 mas não exatamente por causa do
truncamento (ver a tolerância em `test_match_probabilities_sum_to_one`). Times não vistos na calibração
histórica levantam `KeyError` — quem chama (`main.py::_selection_candidates`) captura isso por evento e
pula em vez de derrubar a execução inteira, já que os nomes dos times na odds API e no CSV histórico
precisam bater exatamente (ver `data/team_aliases.py` abaixo).

**Combos do mesmo jogo**: `match_probabilities()` também devolve 6 probabilidades conjuntas
resultado×total (`home_win_and_over_2_5`, `home_win_and_under_2_5`, `draw_and_over_2_5`,
`draw_and_under_2_5`, `away_win_and_over_2_5`, `away_win_and_under_2_5`), somadas direto da mesma grade —
probabilidade CONJUNTA exata, não o produto ingênuo das marginais (que assumiria independência entre
resultado e total, falso: mandante goleando empurra pro over). Ver
`test_same_game_combo_not_naive_product_of_marginals`. **Ainda sem consumidor em `main.py`** — não
confirmamos se a Odds API tem mercado cotável de "resultado + total" combinado pra futebol; os campos
existem e são testados, prontos pra quando/se houver odd real pra comparar (ver
docs/estrategias_extraidas_livros.md, item 2).

**Calibração** (`backtest/calibration.py`, rodável via `python -m backtest.run_calibration_check`):
separa o histórico por data (80/20 treino/teste) e compara probabilidade prevista com frequência
observada, por faixa de 10 p.p., pra cada resultado. Achado real (documentado em
docs/estrategias_extraidas_livros.md, item 3): o modelo tende a SUPERESTIMAR a própria confiança
quando prevê um favorito forte (mandante ou visitante > ~60% de probabilidade) — a faixa mais alta
prevista sistematicamente teve frequência real menor, em quase todas as 6 fontes de dado
independentes. Nenhuma correção foi aplicada a partir disso ainda.

**Ponderação temporal (`half_life_days`)**: a calibração pesa jogos recentes mais que antigos por
decaimento exponencial (peso cai pela metade a cada `half_life_days`; padrão 1095 = 3 anos, configurável via
`MODEL_HALF_LIFE_DAYS` no `.env`, `None`/`"none"` desativa). Existe porque times historicamente fortes mas
em fase ruim atualmente (ex: Corinthians, vários títulos entre 2005-2017) inflavam demais a força estimada
sem isso — mesmo com a ponderação, alguns EVs continuam artificialmente altos (>50%), porque o modelo ainda
não tem nenhum sinal de forma recente de curtíssimo prazo (últimos 5-10 jogos, lesões etc.); trate EVs muito
altos com desconfiança, não como edge real confirmado — isso fica mais explícito agora porque a própria
mensagem do Telegram tem um rodapé avisando disso (ver `alerts/telegram_notifier.py` abaixo).
`MatchResult.match_date` é opcional — sem data (`None`) o jogo entra com peso 1.0.

### Lógica financeira (`analysis/ev.py`, `analysis/kelly.py`)

Responsabilidades deliberadamente separadas: `ev.py` só compara a probabilidade do modelo com a odd de
mercado (`prob_modelo × odd - 1`); `kelly.py` só dimensiona o stake dado um edge (Kelly fracionário, padrão
25% do Kelly cheio, travado em `MAX_STAKE_FRACTION` da banca). Ambos são funções puras, sem I/O — mantenha
assim, é o que permite testá-los sem mocks.

**Teto de exposição por jogo** (`kelly.py::cap_group_exposure`, `main.py::_cap_match_exposure`): apostas em
mercados diferentes do MESMO jogo não são independentes entre si (dependem do mesmo resultado final —
"empate", "under 2.5" e "ambas não marcam" no mesmo jogo tendem a ganhar ou perder juntas). `capped_stake`
só trava CADA aposta em `MAX_STAKE_FRACTION`; sem esse teto adicional, um jogo com valor em vários mercados
podia concentrar várias vezes esse percentual na banca de uma vez só — foi o que aconteceu de verdade em
08/09/2026 (2 jogos concentraram ~25% da banca sozinhos, 5 picks somando 13.3% num, 4 picks somando 12%
noutro, e os 2 jogos deram errado). Depois de `_picks_from_candidates` montar os picks de um evento,
`_cap_match_exposure` reduz proporcionalmente o stake de todos eles se a soma ultrapassar
`MAX_STAKE_FRACTION` — reaproveita o mesmo número já configurado, sem criar um `.env` novo (decisão do
usuário, opção recomendada apresentada). Não muda quais picks são gerados nem o EV/probabilidade exibidos,
só o tamanho sugerido da aposta.

**Hold sintético** (`ev.py::market_hold`, ver docs/estrategias_extraidas_livros.md item 1): soma das
probabilidades implícitas de um mercado completo, menos 1 — mesmo cálculo que alimenta
`remove_overround`, só que devolvendo o hold em vez das probabilidades normalizadas. `main.py`
(`_market_partitions` + `_synthetic_holds_by_selection`) usa isso pra calcular, por evento, o hold
"sintético" de cada mercado completo (1X2, over/under 2.5, BTTS — dupla chance fica de fora, suas 3
seleções se sobrepõem e não formam uma partição de verdade) pegando a melhor odd de cada seleção,
possivelmente de casas diferentes. `Pick.market_hold` guarda isso (`None` se a partição não tinha todas
as pernas cotadas). Aparece no Telegram como `🔀 hold ±X%` ao lado do EV — hold baixo/negativo é sinal
de que as casas discordam entre si, **independente** da nossa própria estimativa de probabilidade.
Puramente informativo, não filtra nem muda o sizing de stake.

### Fronteira de acesso a dados

`data/odds_client.py` e `data/historical_loader.py` são os únicos módulos que saem do processo (HTTP e CSV
no filesystem, respectivamente).

**`OddsAPIClient`** (`data/odds_client.py`) aceita uma **lista** de chaves (`api_keys`, de
`config.ODDS_API_KEYS` = `[ODDS_API_KEY] + ODDS_API_KEYS_EXTRA`) e troca automaticamente pra próxima quando
uma responde 401/402/429 (crédito esgotado/limite atingido) — o índice da chave atual persiste entre
chamadas do mesmo client (não volta pra chave 0 sozinho). Dois métodos:
- `get_upcoming_odds(sport_key)` — em lote, `regions × markets` créditos, todos os jogos futuros da liga
  numa chamada só (não é por jogo).
- `get_event_odds(sport_key, event_id, markets)` — mercados adicionais (BTTS, dupla chance) **por evento**,
  mesma fórmula de créditos mas cobrada por partida. `main.py::_with_additional_markets` só chama isso pros
  jogos que **já passaram no filtro de hoje** (não pra todo jogo futuro retornado pela chamada em lote) —
  é o que mantém o custo sob controle. Controlado por `config.ADDITIONAL_MARKETS` (`"none"` desativa).

Não adicione chamadas extras sem considerar o orçamento de créditos do free tier (500/mês por chave). Com 9
competições + mercados adicionais nos jogos de hoje, uma execução típica fica na faixa de 20-60+ créditos
dependendo de quantos jogos existem no dia — ainda dá folga pra rodar 1x/dia dentro do free tier de uma
chave só; `ODDS_API_KEYS_EXTRA` existe pra somar outra conta se isso um dia não bastar.

**Dados históricos**: um CSV por competição em `HISTORICAL_DATA_DIR/{sport_key}.csv` (convenção de nome —
`main.py::_load_models` deriva o caminho direto do sport_key, sem mapeamento explícito no config). Formato
de colunas detectado automaticamente (`_COLUMN_ALIASES` em `historical_loader.py`):
`HomeTeam`/`AwayTeam`/`FTHG`/`FTAG` (football-data.co.uk / xgabora/Club-Football-Match-Data, ligas
europeias) ou `mandante`/`visitante`/`mandante_Placar`/`visitante_Placar` (adaoduque/Brasileirao_Dataset,
Brasileirão). Coluna de data (`Date`/`data`, também autodetectada, aceita `dd/mm/yyyy`, `dd/mm/yy` e
`yyyy-mm-dd`) alimenta a ponderação temporal do modelo. Linhas malformadas são silenciosamente ignoradas; um
CSV com colunas de nenhum formato reconhecido levanta `ValueError`.

**As 3 copas UEFA (`soccer_uefa_champs_league`, `_europa_league`, `_europa_conference_league`) compartilham
o mesmo CSV combinado** das 5 ligas domésticas europeias (concatenação simples, sem normalizar a diferença
de padrão de gols entre ligas) — é uma simplificação deliberada, não um modelo por-liga de verdade. Times de
países fora dessas 5 ligas (Porto, Ajax, Celtic etc.) não têm histórico e são pulados como qualquer time sem
dado. Ver o roadmap do README ("Normalização entre ligas") — melhoria conhecida, não implementada.

**Nomes de times (`data/team_aliases.py`)**: a Odds API e os CSVs históricos usam nomenclaturas diferentes
pro mesmo time (ex: "Botafogo" vs. "Botafogo-RJ", "Manchester United" vs. "Man United"). `TEAM_ALIASES` é um
dict único global (nomes não colidem entre competições) mapeando Odds API → CSV, aplicado só na hora de
consultar o modelo (`main.py::_selection_candidates`) — os nomes exibidos no Telegram e salvos em `Pick`
continuam sendo os originais da Odds API. Times genuinamente sem histórico no CSV (recém-promovidos, ou
clubes de ligas não cobertas) não têm solução por alias — continuam sendo pulados via `KeyError`, o que é o
comportamento correto. **Cuidado com nomes duplicados dentro da própria fonte histórica**: o dataset
xgabora tinha o mesmo time grafado de duas formas em temporadas diferentes (`"Nott'm Forest"` /
`"Nottm Forest"` pro Nottingham Forest, `"M'gladbach"` / `"MGladbach"` pro Borussia Mönchengladbach) —
isso fragmenta o histórico do time em duas chaves e já foi corrigido diretamente nos CSVs gerados; ao
regerar esses CSVs no futuro, rode um diff de nomes parecidos (`difflib.get_close_matches`) antes de
assumir que está limpo.

### Filtro de hoje e fuso horário (`data/schedule.py`)

BRT é tratado como offset fixo UTC-3 (`timezone(timedelta(hours=-3))`) — Brasil não observa horário de
verão desde 2019, então não precisa de `zoneinfo`/`pytz`. `today_brt()` é usado tanto pra calcular "ontem"
(`resolve_yesterday`) quanto "hoje" (`build_todays_picks`, chave de armazenamento em `PicksStore`) — antes
dessa mudança, `main.py` usava `date.today()` implicitamente em UTC (o runner do GitHub Actions roda em
UTC), o que só coincidia com o dia certo em BRT por sorte de horário; agora é consistente e explícito em
todo o pipeline. `is_same_day_brt` compara o `commence_time` (ISO, UTC, formato da Odds API) convertido pra
BRT contra uma data de referência.

### Checagem de notícias (`data/news_check.py`)

Opcional (requer `config.ANTHROPIC_API_KEY`; sem ela `main.py::_check_news` retorna `{}` direto, sem
chamar nada) — a **primeira dependência paga** do projeto, ao contrário de todo o resto (Odds API free
tier, Telegram grátis). `NewsChecker.check_match()` usa `client.messages.create` com a tool
`web_search_20260209` (modelo `claude-opus-5`, `output_config={"effort": "low"}` pra manter rápido/barato —
é uma tarefa de extração simples, não precisa de raciocínio pesado) perguntando se há lesão/suspensão/
desfalque relevante pro confronto, e devolve no máximo 2 frases em português ou `None`.

**Puramente informativo — nunca ajusta `model_probability`, EV ou stake.** Foi uma decisão explícita do
usuário depois de eu apresentar as opções: traduzir "jogador X machucado" num ajuste numérico na força do
time seria uma heurística subjetiva demais pra confiar sem supervisão. O aviso só aparece como uma linha
extra (`⚠️ <i>...</i>`) na mensagem do Telegram, abaixo do horário/confronto — ver `send_daily_picks` em
`alerts/telegram_notifier.py`.

Chamado só pros jogos que **já geraram pick** (`main.py::_check_news`, um por partida, não por pick — um
jogo pode ter vários picks) — não pra todo jogo de hoje, o que manteria o custo baixo mesmo em dias
movimentados. Nunca levanta exceção (`check_match` captura tudo e retorna `None` em erro) — é uma etapa
opcional, não pode derrubar o envio dos picks.

**Cuidado ao processar a resposta**: `response.content` vem com múltiplos blocos de texto quando o modelo
usa a ferramenta de busca — um bloco de narração antes ("vou pesquisar...") e a resposta final depois.
Pegue só o **último** bloco de texto (`text_blocks[-1]`), nunca concatene todos — foi um bug real encontrado
e corrigido nesta sessão (o texto ficava com "I'll search for..." colado na frente do aviso de verdade).

### Mensagens do Telegram (`alerts/telegram_notifier.py`)

Agrupadas por competição e depois por jogo (`_COMPETITION_LABELS` dá nome+emoji por `sport_key`, com
fallback genérico pra competição sem entrada no dict — não trava se `SPORT_KEYS` ganhar uma competição
nova). `send_daily_picks` recebe `games_today` (contagem de jogos de hoje considerados, não só os que
viraram pick) pra diferenciar "sem jogos hoje" de "teve jogo mas sem valor" na mensagem — vem de
`build_todays_picks`, que retorna `(picks, games_today)` em vez de só a lista de picks. Também recebe
`news_notes` opcional (`dict[match, aviso]`, de `main.py::_check_news`) — se o jogo tiver aviso, aparece
logo abaixo do horário/confronto. Mensagem de picks termina com um rodapé fixo (`_EV_EXPLAINER`) explicando
o que EV significa e avisando que EV muito alto pode ser erro de modelo — reforça o aviso que já está em
"Modelo" acima, agora visível pro usuário final também.

### Armazenamento (`storage/picks_store.py`)

JSON simples indexado por data ISO (calculada em BRT — ver acima), com listas de dataclasses `Pick`
serializadas como valores. `Pick` é o tipo de registro compartilhado que atravessa todo o pipeline
(avaliação de odds → armazenamento → resolução de resultado → formatação do Telegram → backtest). Ele
acumula os estados "previsto" e "resolvido" via os campos opcionais `result`/`profit_units`, em vez de ser
dividido em tipos separados — expect que essa dataclass seja lida e escrita bem além de `storage/`. O README
deixa claro que isso é propositalmente simples e deve ser trocado por SQLite/Postgres se o histórico crescer.

### Automação

**Atenção à raiz do repo**: `sports-betting/` é uma subpasta dentro do repositório Git `TradeBot` (o
remote é `MagroDaniel/TradeBot`) — não é a raiz. `.github/workflows/daily_picks.yml` fica na raiz do repo
(`TradeBot/.github/...`), não dentro de `sports-betting/.github/...`; procure lá se for mexer nele. O
workflow roda: cron diário (10h UTC = 07h BRT) + `workflow_dispatch` (disparo manual),
`working-directory: sports-betting`, instala dependências, roda `python main.py` com as credenciais como
secrets, e commita+pusha `storage/picks.json` de volta (runners são efêmeros). Os secrets estão configurados
no GitHub e um run manual (`workflow_dispatch`) já confirmou o pipeline de ponta a ponta — commit automático
de `github-actions[bot]` no repo e mensagens reais recebidas no Telegram. Repo requer "Read and write
permissions" em Settings → Actions → General → Workflow permissions (senão o `git push` final do job falha)
— já habilitado. **Nota**: se um workflow novo/editado não aparecer na aba Actions mesmo estando no branch
padrão, é só falta de reindexação do GitHub — basta um novo push tocando o arquivo do workflow pra ele
aparecer (aconteceu uma vez neste repo).

## Status atual

Bot 100% operacional de ponta a ponta, com todas as mudanças abaixo já testadas com dados/credenciais reais
(local e via GitHub Actions):

- Setup inicial completo: `.env`, ambiente local, GitHub Actions com secrets configurados.
- 9 competições ativas (Brasileirão + 5 ligas europeias + 3 copas UEFA), cada uma com seu próprio CSV
  histórico e modelo calibrado — ver tabela no README.
- Filtro de "só jogos de hoje em BRT" — corrigido bug onde o bot mostrava jogos de dias futuros.
- Horário de envio: 7h BRT (mudou de 8h).
- Mercados expandidos: além de 1X2 e over/under 2.5, agora também BTTS (ambas marcam) e dupla chance —
  buscados por evento só pros jogos já filtrados como "de hoje".
- Suporte a múltiplas chaves da Odds API (`ODDS_API_KEYS_EXTRA`) com fallback automático quando uma fica
  sem crédito.
- Mensagens do Telegram redesenhadas: agrupadas por competição e por jogo, mais emojis, rodapé explicando
  o que é EV.
- Ponderação temporal no modelo (`half_life_days`) — reduz mas não elimina EVs artificialmente altos.
- Checagem de notícias opcional via Claude + busca na web (`data/news_check.py`) — aviso informativo de
  lesão/suspensão ao lado do pick, sem ajustar EV/probabilidade. Primeira dependência paga do projeto.
- Telegram migrado de chat pessoal pra grupo (`TELEGRAM_CHAT_ID` negativo) — testado e confirmado.

Pendências conhecidas (decisões conscientes, não bugs):
- Teto de EV (`EV_MAX_THRESHOLD`) cogitado como segunda camada de segurança contra EVs artificialmente
  altos — não implementado, usuário prefere revisar manualmente antes de apostar.
- Modelo combinado das copas UEFA não normaliza diferença de padrão de gols entre as 5 ligas domésticas
  (ver "Fronteira de acesso a dados" acima) — simplificação deliberada, não uma modelagem por-liga completa.
- `docs/estrategias_extraidas_livros.md` lista ideias extraídas de 3 livros de referência sobre apostas
  esportivas (`docs/referencias/`). Hold sintético entre casas (`analysis/ev.py::market_hold`, ver
  "Lógica financeira" abaixo) e combos do mesmo jogo (`PoissonModel.match_probabilities`, ver "Modelo"
  abaixo) já foram implementados. Viés de favorito forte/empate foi investigado com uma checagem real de
  calibração (`backtest/calibration.py`) — achado real documentado no arquivo, nenhuma correção aplicada
  ainda (decisão do usuário). CLV foi adiado — usuário optou por manter a arquitetura de execução 1x/dia
  como já estava decidido, em vez de pagar o custo extra (segunda leitura de odds ou plano pago da Odds
  API) só pra ter uma odd de "fechamento" pra comparar.

## Projeto irmão

`../crypto-daytrade/` (raiz do repo `TradeBot`) — bot que alerta sobre novas listagens de criptomoeda na
Binance. Mesma filosofia (só análise/alerta, sem executar nada sozinho), mas **sem** o equivalente do EV —
não existe uma fórmula matemática objetiva pra "essa moeda nova vai bombar" (diferente daqui, onde EV
compara a probabilidade do modelo contra a odd de mercado). Tem seu próprio bot/grupo do Telegram e roda a
cada 15-30 min (não 1x/dia — listagem de cripto não tem "horário de jogo"). Ver o `CLAUDE.md` de lá pra
detalhes.
