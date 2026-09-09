# Estratégias extraídas dos livros de referência

Leitura dos 3 PDFs em `docs/referencias/` (texto extraído via `pdftotext`, ~580 páginas no total,
mais uma resenha de 5 páginas). Este documento resume o que é **potencialmente aplicável** ao
`sports-betting`. Mesmo processo já usado no `crypto-daytrade`
(ver `crypto-daytrade/docs/estrategias_extraidas_livros.md`): livro é hipótese, o que decide é
teste contra dado real — nesse caso, os itens 1 e 2 foram implementados (são features
autocontidas, sem exigir re-treino ou mudança de critério de decisão), o item 3 foi investigado
com uma checagem real contra o histórico (resultado abaixo), e o item 4 segue pendente de uma
decisão de produto (custo de API adicional).

**Status**: ✅ item 1 (hold sintético) implementado — `analysis/ev.py::market_hold`,
`main.py::_synthetic_holds_by_selection`, exibido no Telegram. ✅ item 2 (combos do mesmo jogo)
implementado — `model/poisson_model.py::match_probabilities` ganhou os 6 combos resultado×total,
ainda sem uso em picks reais (ver ressalva no item). ✅ item 3 investigado — achado real abaixo,
nenhuma mudança de código aplicada a partir dele ainda (é sobre calibração do modelo, uma decisão
de correção seria um passo à parte). ⏳ item 4 aguardando decisão do usuário.

## Livros lidos

1. **Soccermatics** (David Sumpter, arquivo `Soccermatics_Sumpter.pdf`, ~340 páginas) — livro de
   divulgação matemática sobre futebol; os capítulos 1, 11-13 cobrem exatamente o que o bot faz
   (Poisson, odds, EV, Kelly), incluindo um experimento real do autor apostando com dinheiro
   próprio por uma temporada.
2. **The Logic of Sports Betting** (Ed Miller & Matthew Davidow, arquivo
   `The_Logic_of_Sports_Betting_Miller_Davidow.pdf`, ~240 páginas) — livro moderno e bem mais
   técnico, focado no mercado americano (NFL/NBA/MLB) mas com conceitos de eficiência de mercado
   que se aplicam a qualquer esporte, incluindo futebol.
3. **Academic Review: The Expected Goals Philosophy** (arquivo
   `Academic_Review_Expected_Goals_Philosophy_Tippett.pdf`, 5 páginas) — não é o livro original de
   James Tippett, é uma **resenha acadêmica** dele (gerada por IA, a julgar pelo estilo). Cobre xG,
   xP ("Justice Table"), xA e o caso Brentford FC/Smartodds. Útil como resumo, mas secundário aos
   outros dois — o bot não tem fonte de dados de xG (ver "Não aplicável" abaixo).

## Ideias com maior relação esforço/retorno (ordenadas por prioridade sugerida)

### 1. ✅ Hold sintético entre casas como sinal de confiança extra — implementado
**Fonte: Logic of Sports Betting, cap. "Betting The Best Price" / "Chopping The Hold".**

O livro descreve o conceito central de "hold sintético": em vez de olhar o hold de uma casa só,
você pega a melhor odd de cada seleção **entre casas diferentes** e soma as probabilidades
implícitas resultantes. Se essa soma ficar perto de 100% (ou abaixo), as casas estão discordando
o suficiente entre si pra que apostar "às cegas" nesse mercado já não perca dinheiro no longo
prazo — é a ideia mais central do livro ("get the hold to zero").

O bot **já faz metade do trabalho**: `main.py::_best_odds_by_selection` já pega a melhor odd por
seleção entre todas as casas retornadas pelo evento — só descarta a informação de quão discordantes
as casas estavam. Dá pra calcular o hold sintético do mercado 1X2 de cada evento (soma das
probabilidades implícitas das 3 melhores odds, cada uma podendo vir de uma casa diferente) sem
nenhuma chamada de API nova — o dado já está ali.

**Uso proposto**: não como filtro que bloqueia picks (mudaria o critério de decisão do bot, que já
é validado), mas como **contexto extra no pick** — ex: mostrar o hold sintético do mercado junto do
pick no Telegram, ou logar pra revisão manual. Hold sintético baixo/negativo é um sinal
*independente* do modelo de Poisson (vem da discordância do mercado, não da nossa própria
estimativa) de que aquele mercado específico está "mais aberto" — complementa, não substitui, o EV
calculado pelo modelo.

**Implementado**: `analysis/ev.py::market_hold(decimal_odds)` (função pura, testada) calcula o
hold de qualquer mercado completo. `main.py::_market_partitions` define as 3 partições completas
do evento (1X2, over/under 2.5, BTTS — dupla chance fica de fora, suas 3 seleções se sobrepõem e
não formam partição de verdade) e `_synthetic_holds_by_selection` calcula o hold sintético de
cada uma (só quando as odds de todas as pernas da partição foram cotadas). `Pick` ganhou o campo
`market_hold` (`None` quando a partição não estava completa, ou em picks salvos antes desse
campo existir). A mensagem do Telegram mostra `🔀 hold +1.8%` ao lado do EV de cada pick, com um
rodapé explicando o conceito (só aparece se algum pick do dia tiver o campo preenchido).
Não virou filtro — é contexto adicional, mesmo espírito do resto do bot (só alerta, decisão é
do usuário).

### 2. ✅ Combos do mesmo jogo usando a probabilidade conjunta exata do modelo — implementado (só no modelo)
**Fonte: Logic of Sports Betting, cap. "Parlays" (seção "Correlated Parlays").**

O livro descreve "parlays correlacionados": combinar duas seleções do **mesmo jogo** (ex: time
manda vencer + over 2.5 gols) é proibido/restrito pela maioria das casas porque essas seleções não
são independentes — um time que goleia tende a jogar acima da linha de gols também. Quando uma
casa permite, é uma aposta historicamente muito mais forte que multiplicar as odds como se fossem
independentes sugeriria.

Isso é relevante aqui porque `PoissonModel.match_probabilities()` **já calcula a grade completa**
de placar a placar (`hg`/`ag`, ver o loop duplo em `model/poisson_model.py`) antes de agregar nos
mercados finais — ela já "sabe" a probabilidade conjunta exata de "mandante vence E over 2.5" (é
só somar as células da grade onde `hg > ag` e `hg + ag > 2`), sem nenhuma suposição de
independência, porque é literalmente a mesma distribuição. Isso é **diferente e mais forte** do que
o bilhete de múltipla que acabamos de implementar (que multiplica probabilidades marginais de jogos
diferentes assumindo independência — correto pra jogos diferentes, mas seria matematicamente errado
pra seleções do mesmo jogo).

**Implementado**: `PoissonModel.match_probabilities()` agora devolve também
`home_win_and_over_2_5`, `home_win_and_under_2_5`, `draw_and_over_2_5`, `draw_and_under_2_5`,
`away_win_and_over_2_5`, `away_win_and_under_2_5` — todos somados direto da grade já calculada
(nenhum loop novo, só mais acumuladores no loop existente). Testes confirmam que são a
probabilidade conjunta exata, não o produto ingênuo das marginais (`test_same_game_combo_not_naive_product_of_marginals`
falharia se alguém "simplificasse" isso por engano).

**Ainda não vira pick real**: não confirmamos se a The Odds API oferece um mercado cotável de
"resultado + total" combinado (`same game parlay`) pra futebol no free tier — sem isso, não tem
odd de mercado pra comparar e calcular EV. Os campos ficam disponíveis no modelo (testados,
prontos pra uso), mas `main.py` ainda não os consome. Confirmar isso na documentação da Odds API
é o próximo passo antes de virar pick de verdade.

### 3. ✅ Viés de favorito forte/empate equilibrado — investigado, achado real (diferente do esperado)
**Fonte: Soccermatics, cap. 12 ("Putting My Money Where My Mouth Is").**

Sumpter testou, com dados reais da Premier League 2014/15, que:
- Jogos com odd de vitória do mandante entre 1.33 e 1.43 (favorito forte) venceram **89%** das
  vezes, mas a odd implícita previa só 70-75% — o mercado subestima favoritos fortes.
- Jogos entre times equilibrados (diferença de probabilidade < 10 p.p.) empataram **34.7%** das
  vezes, contra 29.5% implícito pela odd — o mercado subestima empates entre iguais.

Ele testou isso como estratégia isolada ("odds-bias strategy": apostar no favorito quando a
diferença de probabilidade > 40 p.p., ou no empate quando < 15 p.p.) e foi a **única das 5
estratégias que testou que deu lucro consistente** ao longo de 90 jogos — as outras (índice tipo
Elo, "especialista" humano, indicador de performance via xG simplificado) perderam dinheiro ou
empataram.

Isso é uma hipótese de literatura acadêmica (o livro cita estudos prévios), não uma descoberta
nova, e o próprio autor avisa: **se o viés for divulgado o suficiente, o mercado corrige e ele
some** — não é garantia.

**Ressalva importante**: os CSVs em `HISTORICAL_DATA_DIR` só têm placar, nunca tiveram odds de
mercado — não dá pra repetir o teste do Sumpter (odds do bookmaker vs. resultado real) com esse
dado. O que dá pra testar é uma pergunta relacionada, mas diferente: **o nosso próprio modelo de
Poisson está bem calibrado**, ou tem viés sistemático nalguma faixa de probabilidade?

**Implementado e executado**: `backtest/calibration.py` (função pura, testada) separa os jogos de
cada competição por data (80% mais antigos pra treino, 20% mais recentes pra teste, nunca vistos
pelo `fit()`), calibra o modelo só com o treino e compara a probabilidade prevista com a
frequência real observada, em faixas de 10 pontos percentuais, pra cada resultado (mandante/
empate/visitante). Rodável via `python -m backtest.run_calibration_check`.

**Resultado real, contra as 6 fontes de dado independentes** (Brasileirão + 5 ligas europeias; as
3 copas UEFA compartilham o mesmo CSV combinado — não contam como evidência extra):

> **O nosso modelo tende a SUPERESTIMAR a própria confiança quando prevê um favorito forte**
> (mandante ou visitante com probabilidade prevista > ~60%) — na faixa de 0.6 a 0.9 de
> probabilidade prevista, a frequência real de vitória ficou abaixo do previsto em praticamente
> todas as competições, de forma consistente:
> - Brasileirão: previsto 0.64-0.72 → observado 0.59-0.66 (gap de -5 a -7 p.p.)
> - Premier League: previsto 0.64-0.73 → observado 0.56-0.73 (gap de até -10 p.p. na faixa 0.6-0.7)
> - Ligue 1: previsto 0.75-0.83 → observado 0.66-0.75 (gap de -8 a -9 p.p.)
> - Serie A (Itália): previsto 0.83-0.93 → observado 0.57-0.61 (gap de até -35 p.p., mas amostra
>   pequena — 64 e 21 jogos nesses bins específicos, tratar com cautela)
> - La Liga: mais ruído (ora acima, ora abaixo), sem viés claro na cauda alta
> - Bundesliga: a mais bem calibrada das 6 — gaps pequenos (< 5 p.p.) em quase todas as faixas
>
> O mesmo padrão aparece, mais fraco, pra vitórias fora de casa em faixa alta de probabilidade.
> Já os empates estão razoavelmente bem calibrados nas faixas com volume de dado suficiente
> (~20-30% previsto, onde mora a maior parte da amostra) — gaps de 1-4 p.p., dentro do ruído.

Isso é o **oposto** do que Sumpter achou pro mercado (que subestima favoritos fortes) — não é
comparável diretamente (são perguntas diferentes: viés do mercado vs. calibração do nosso
modelo), mas é um achado real e acionável por si só: quando o modelo prevê um favorito muito
forte, ele tende a estar mais confiante do que deveria. Isso é consistente com — e dá um número
concreto para — o aviso que já existe no rodapé do Telegram (`_EV_EXPLAINER`: "EV muito alto
também pode ser sinal de erro do modelo, não de oportunidade real").

**Nenhuma correção foi aplicada** — isso é uma investigação, não uma feature. Uma correção
(ex: um fator de encolhimento pra probabilidades extremas, "puxando" previsões muito altas um
pouco pra baixo) seria uma mudança de comportamento do modelo que merece sua própria validação
(será que reduz o ROI real dos picks já resolvidos em `storage/picks.json`, ou só parece melhor
na teoria?) — decisão pro usuário tomar, não algo pra aplicar sozinho a partir de uma única
checagem de calibração.

### 4. Closing Line Value (CLV) — já está no roadmap do README, aqui está o método concreto
**Fonte: Logic of Sports Betting, cap. "Market Agreement and Resistance" e "How Do I Know If I'm
Winning?".**

O README já lista CLV como melhoria conhecida não implementada. O livro dá o método exato: comparar
a odd que você apostou com a odd da mesma seleção **no fechamento do mercado** (mais perto do
início do jogo). Se em média você bate a odd de fechamento por pelo menos metade do hold da casa,
ao longo de centenas de apostas, isso é evidência de edge real — descolado da variância de
curto prazo de só olhar taxa de acerto.

**Obstáculo real, não só de código**: o bot busca as odds só 1x por dia, de manhã (`7h BRT`), pro
mesmo dia — não há uma segunda leitura perto do horário do jogo pra servir de "fechamento". Pra
implementar CLV de verdade seria preciso, ou (a) uma segunda chamada à Odds API perto do
`commence_time` de cada jogo (custo de crédito adicional e mudança de arquitetura — hoje é um job
único), ou (b) o endpoint de odds históricas da própria Odds API, que é recurso pago (não faz parte
do free tier atual). Vale registrar como pendência de decisão de produto, não implementar sem
decidir isso com o usuário primeiro.

### 5. Mercados principais vs. mercados derivados ("attack surface") — valida decisão já tomada, sugere possível expansão
**Fonte: Logic of Sports Betting, cap. "Beating The Odds" (seção "Disadvantage #1: Attack
surface").**

O livro argumenta que mercados principais e líquidos (1X2 em ligas grandes) são o "ponto forte" da
casa — muito bem precificados, difícil achar valor. Mercados derivados/secundários (o livro cita
handicaps alternativos, primeiro tempo, props) são a "superfície de ataque" — menos vigiados,
mais chance de preço errado.

Isso é consistente com a decisão já tomada de incluir BTTS e dupla chance via `ADDITIONAL_MARKETS`
(`config.py`) — já são mercados "derivados" em relação ao 1X2/over-under principal. Não é uma
mudança de código, é validação de uma escolha já feita; only vale investigar se a The Odds API
oferece mais mercados derivados pra futebol (ex: handicap asiático) que ainda não estão em
`ADDITIONAL_MARKETS`.

## O que NÃO parece aplicável (e por quê)

- **Modelos baseados em xG** (Tippett, Soccermatics cap. 13 "Unexpected Goals") — precisam de dados
  de posição/qualidade de chute por partida (Opta ou similar), que não fazem parte de nenhuma fonte
  de dados que o bot já usa (nem a Odds API, nem os CSVs de `historical_loader.py`, que só têm
  placar agregado). O próprio Sumpter, depois de testar por 3 semanas, **abandonou** a estratégia
  baseada em xG do seu modelo de apostas por alta variância e falta de lucro demonstrado — não é só
  uma barreira de dado, é um resultado empiricamente fraco mesmo pra quem tinha o dado.
- **Índices de rating tipo Elo** ("Euro Club Index", Soccermatics cap. 12) — o autor testa e mostra
  que, sozinho, um índice desse tipo só acompanha a precisão do mercado sem gerar lucro (perde pro
  hold da casa a uma taxa parecida com apostar aleatório). Reforça que o que o bot já faz — modelo
  calibrado por competição comparado contra odd, não só "forma recente" — é a abordagem certa;
  não sugere trocar o Poisson por um Elo.
- **Perseguição de linha ("chasing steam"), resistência de mercado, apostas ao vivo/derivativos
  exóticos** — dependem de monitorar o mercado continuamente ao longo do dia (múltiplas leituras de
  odds, não uma só de manhã) e de mercados que a The Odds API free tier não cobre bem para futebol.
  Fora do orçamento de créditos e da arquitetura "roda 1x/dia" — decisão já tomada e documentada no
  `CLAUDE.md`, não reabrir sem motivo.
- **Dicas de especialista humano ("Strategy 4", Soccermatics)** — o próprio autor testou e a
  estratégia perdeu dinheiro; ele cita outros estudos mostrando que "especialistas" geralmente
  perdem pra odd do mercado. Não há nada aqui pra incorporar.
- **Regras específicas de cassino americano** (conversão de odds US, parlay cards, limites de
  aposta por casa, contas múltiplas) — específico do mercado de apostas dos EUA, sem equivalente
  relevante pro escopo do bot (futebol, Odds API, Telegram).

## Próximos passos sugeridos

Itens 1, 2 e 3 já foram trabalhados (ver status de cada um acima). O que sobra:
1. Confirmar se a The Odds API tem algum mercado de "resultado + total" combinado pra futebol
   (item 2) — sem isso os combos do modelo continuam sem uso real em picks.
2. Decidir se vale investigar uma correção de calibração pra favoritos fortes (item 3) — e, se
   sim, validar contra `storage/picks.json` real antes de mudar `model/poisson_model.py`.
3. CLV (item 4) é decisão de produto (custo de API extra) antes de ser tarefa de código — ver
   opções levantadas com o usuário.
