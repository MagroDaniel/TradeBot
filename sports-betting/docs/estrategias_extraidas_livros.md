# Estratégias extraídas dos livros de referência

Leitura dos 3 PDFs em `docs/referencias/` (texto extraído via `pdftotext`, ~580 páginas no total,
mais uma resenha de 5 páginas). Este documento resume o que é **potencialmente aplicável** ao
`sports-betting` — nada aqui foi implementado ainda. Mesmo processo já usado no `crypto-daytrade`
(ver `crypto-daytrade/docs/estrategias_extraidas_livros.md`): **nenhuma ideia daqui vai pra
produção sem passar pelo `backtest/backtester.py` primeiro** (ou, pro item de CLV, sem antes
resolver a questão de dados descrita abaixo) — livro é hipótese, backtest é quem decide.

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

### 1. Hold sintético entre casas como sinal de confiança extra — `analysis/ev.py` ou novo módulo
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

→ **Candidato mais barato de testar**: função pura nova em `analysis/`, sem I/O, testável isolada
como `ev.py`/`kelly.py` já são. Baixo esforço, zero custo de crédito de API adicional.

### 2. Combos do mesmo jogo usando a probabilidade conjunta exata do modelo — `model/poisson_model.py`
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

→ **Candidato de esforço baixo/médio**: adicionar alguma combinação de seleções do mesmo jogo (ex:
`home_win_and_over_2_5`) ao dict retornado por `match_probabilities()`, reaproveitando a grade que
já existe — não precisa de novo dado, só de mais uma soma dentro do loop que já roda. O desafio
real não é o modelo, é achar odd de mercado pra comparar: a The Odds API (free tier) provavelmente
não oferece o mercado combinado (`same game parlay`) pra futebol como mercado cotado — precisa
confirmar se `ADDITIONAL_MARKETS` aceita algo do tipo antes de prometer isso como pick real; sem
isso, funciona só como estatística informativa (mesmo espírito do bilhete de múltipla: prioriza
"o modelo sabe algo a mais", não necessariamente vira aposta cotável).

### 3. Viés de mercado em favoritos fortes e empates equilibrados — hipótese pra investigar, não implementar direto
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
some** — não é garantia. Não deveria virar um filtro automático sem validação própria.

→ **Candidato de teste**: rodar essa mesma checagem (odds implícitas vs. resultado real) sobre o
histórico já carregado em `HISTORICAL_DATA_DIR`, pra ver se o viés aparece nos dados que o bot já
usa, antes de cogitar qualquer mudança de código. Isso é um trabalho de `backtest/`, não de
`model/`.

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

Nenhuma mudança de código ainda — na ordem de esforço/retorno acima:
1. Hold sintético entre casas (item 1) é o mais barato e mais alinhado com o que o bot já faz — bom
   primeiro passo se o usuário topar.
2. Combos do mesmo jogo via grade de Poisson (item 2) é o mais interessante do ponto de vista de
   modelo, mas depende de confirmar se há mercado cotável pra comparar antes de virar um pick real.
3. Viés de favorito forte/empate equilibrado (item 3) precisa de validação com os dados históricos
   já existentes antes de qualquer mudança de código — é hipótese de literatura, não fato
   confirmado pros nossos dados.
4. CLV (item 4) é decisão de produto (custo de API extra) antes de ser tarefa de código.
