# Estratégias extraídas dos livros de referência

Leitura dos 3 PDFs em `docs/referencias/` (texto extraído via `pdftotext`, ~760 páginas no total).
Este documento resume o que é **potencialmente aplicável** ao `crypto-daytrade` — nada aqui foi
implementado ainda. Seguindo o processo já estabelecido no projeto (ver "Backtest walk-forward" no
CLAUDE.md, motivado pelo episódio do ADX), **nenhuma ideia daqui vai pra produção sem passar pelo
`backtest/run.py` primeiro** — livro é hipótese, backtest é quem decide.

## Livros lidos

1. **Análise Técnica** (Partes 1 e 2, Editora Saraiva) — livro-texto brasileiro abrangente: Dow,
   padrões gráficos, indicadores atrasados/antecedentes, stops, psicologia, estratégias.
2. **Trading Price Action Trends** (Al Brooks, tradução automática/portuguesa, qualidade de tradução
   ruim em trechos, mas terminologia dá pra entender) — leitura pura de price action (sem indicadores),
   referência clássica no assunto.

## Do livro de Análise Técnica

### Filtros de média móvel (cap. 8.2.7) — os mais diretamente aplicáveis
O livro lista 5 filtros pra reduzir sinal falso de cruzamento de média, sem precisar trocar a
estratégia base:
- **Filtro 1**: exigir que o **corpo inteiro** da vela (não só o fechamento) esteja acima/abaixo da
  EMA no candle do cruzamento.
- **Filtro 2**: regra de penetração — só confirma quando o preço rompe a média por um % mínimo.
- **Filtro 3**: exigir confirmação por rompimento de padrão gráfico (ex: fundo/topo duplo).
- **Filtro 4**: filtro de tempo — aguardar 1-3 candles após o cruzamento pra confirmar (evita reverter
  na "faca" do próprio candle de cruzamento).
- **Filtro 5**: bandas/envelope ao redor da média.

→ **Candidato de backtest mais barato de testar**: Filtro 1 (corpo inteiro além da EMA) e Filtro 4
(esperar 1-2 candles) são triviais de implementar em cima do `generate_signal()` atual e podem reduzir
sinal falso sem mudar a lógica de EMA9/EMA21+RSI já validada.

### RSI com faixas dinâmicas por regime (cap. 9.5.1, Constance Brown)
O livro cita que RSI não necessariamente oscila 0-100 de forma simétrica: em tendência de alta tende a
ficar entre 40-90 (40-50 vira suporte), em tendência de baixa entre 10-60 (50-60 vira resistência). O
bot hoje usa faixas fixas (`LONG_RSI_RANGE`/`SHORT_RSI_RANGE`). Como o bot **já** calcula tendência do
1h (`confirms_higher_timeframe_trend`), dá pra testar deslocar a faixa de RSI aceita conforme esse
regime já detectado, em vez de faixa fixa — não precisa de indicador novo, só reaproveitar o que já
existe.

### Divergência (RSI/MACD) — sinal que o bot não usa hoje
Divergência entre topos/fundos do preço e do oscilador é citada repetidamente como "o melhor sinal" de
RSI/MACD/estocástico. O bot atual não olha divergência nenhuma. Seria um **tipo de sinal novo**, não um
filtro do que já existe — maior esforço de implementação, mas testável isoladamente no backtest antes
de mexer em produção.

### Stop ATR: múltiplo maior + trailing (cap. 17.2.6.3)
Dois pontos relevantes que destoam do que o bot faz hoje:
- O livro cita que day traders costumam usar **múltiplo de ATR maior** (3-4x) que o `ATR_STOP_MULTIPLIER`
  atual do bot (1.5x) — vale testar variantes com múltiplo maior no backtest, já que o bot está fixo em
  1.5x sem ter testado outros valores.
- O stop ATR do livro é **trailing** (a distância anda com o preço, recalculada a cada candle),
  enquanto o bot fixa o stop no momento da entrada e nunca move. Um stop móvel deixaria vencedores
  correrem mais — isso muda o cálculo de R-multiple e merece um variant separado no `backtest/engine.py`
  (não é um parâmetro simples, é uma mudança de mecânica de saída).

### Sistemas de 3 médias — Agulhada do Didi / Bow tie (cap. 8.2.8)
Duas variações de sistema com 3 médias (ex: MMS 3/8/21, ou MMS10/MME20/MME30) que exigem as três médias
convergirem e depois se separarem na ordem certa antes de confirmar tendência — mais seletivo que
cruzamento de 2 médias. Interessante como **alternativa** ao EMA9/EMA21 atual pra comparar no backtest,
não como adição — são estratégias de entrada concorrentes, não filtros complementares.

### Canal Donchian — sinal de breakout, não de cruzamento
Sistema baseado em rompimento de máxima/mínima de N períodos, sem médias. Seria um **tipo de sinal
alternativo** (entrada no rompimento de range, não em cruzamento de EMA) — vale como variante a comparar
no backtest, mesmo espírito de quando o filtro de 1h foi comparado contra o baseline.

## Do livro de Price Action (Al Brooks)

Vocabulário e conceitos, sem indicadores — poderia complementar (não substituir) a lógica atual:

### Qualidade da "barra de sinal" (signal bar)
Conceito central do livro: uma barra de reversão "boa" fecha perto do extremo oposto à sombra (ex: barra
de reversão de alta fecha perto da máxima, com sombra inferior grande). O candle que dispara o
cruzamento EMA9/EMA21 hoje não é avaliado por formato nenhum — só pelo cruzamento + RSI. Dá pra testar
um filtro adicional exigindo que o candle do sinal tenha corpo/fechamento "forte" na direção do sinal
(ex: fechamento no terço superior do candle pra long) — testável como filtro extra em cima do sinal
existente, barato de implementar.

### "Always-in" (sempre-dentro) — mesma ideia do filtro de 1h já adotado
O conceito de que o mercado está sempre "sempre comprado" ou "sempre vendido" (nunca neutro) e que só
vale operar a favor desse viés é, na prática, o mesmo raciocínio por trás do
`confirms_higher_timeframe_trend()` que já foi validado por backtest e está em produção. Não é uma ideia
nova pro projeto, é uma confirmação de que o caminho já escolhido (filtro de tendência do timeframe
maior) está alinhado com a literatura — reforça, não abre trabalho novo.

### Trading range vs. tendência — possível substituto pro ADX rejeitado
O livro dá bastante peso a reconhecer quando o mercado está em **trading range** (lateral) vs. tendência
antes de confiar em qualquer sinal — exatamente o que o ADX tentava fazer e que o backtest (60 e 180
dias) mostrou que **piorou** o resultado (ver CLAUDE.md, "Backtest walk-forward"). O livro sugere
detectar range por **estrutura de preço** (topos e fundos não fazendo máximas/mínimas novas, sobreposição
de barras) em vez de um indicador de fórmula fixa como o ADX. Seria uma forma diferente de tentar o
mesmo objetivo que já falhou uma vez com ADX — vale tentar, mas com expectativa calibrada: o projeto já
tem um precedente de que "filtro de regime" com ADX não funcionou nesse mercado/período, então essa
variante também precisa ser validada com ceticismo antes de qualquer aplicação.

### Alvo por "movimento medido" (measured move)
Em vez de alvo fixo por múltiplo de risco (`RISK_REWARD_RATIO`), o livro usa a distância do impulso
anterior como alvo (projeção do tamanho do último swing). Seria uma forma alternativa de definir o
`target`, testável como variante isolada no backtest.

## Resultado do backtest: filtro de qualidade do candle de sinal (2026-09-09)

Item 1 da lista abaixo foi implementado (`backtest/filters.py::passes_signal_candle_quality_filter`)
e testado contra 60 e 180 dias reais, em cima da produção atual (filtro de 1h):

| Variante | 60d exp(R) / PF / maxDD(R) | 180d exp(R) / PF / maxDD(R) |
|---|---|---|
| + tendência 1h (produção atual) | 0.07 / 1.11 / 93.00 | 0.04 / 1.06 / 195.88 |
| + 1h + qualidade do candle (50%) | 0.07 / 1.11 / 68.00 | 0.03 / 1.05 / 143.07 |
| + 1h + qualidade do candle (65%) | 0.10 / 1.16 / 66.00 | 0.03 / 1.05 / 106.00 |

**Descartado por enquanto** — mesmo critério usado pra rejeitar o combo ADX+1h: na janela de 60 dias
o filtro parecia superar a produção em tudo, mas nos 180 dias a ordem **inverte** (produção com
expectância levemente melhor). Resultado que muda de ranking entre janelas é sinal de amostra
pequena, não edge real. O único ganho consistente nas duas janelas foi redução de drawdown máximo
(sem melhora de expectância que se sustente) — não o suficiente pra justificar a mudança sozinho.
Código fica em `backtest/filters.py` como filtro opcional pra reexplorar depois (ex: testado com
outro período de EMA de referência, ou combinado com outro filtro), mesmo tratamento que o ADX.

## Resultado do backtest: múltiplo de ATR pro stop (2026-09-09)

Item 2 também testado contra 60 e 180 dias reais, em cima da produção atual (filtro de 1h):

| Variante | 60d exp(R) / PF / maxDD(R) | 180d exp(R) / PF / maxDD(R) |
|---|---|---|
| + tendência 1h (produção atual, ATR×1.5) | 0.07 / 1.11 / 93.00 | 0.04 / 1.06 / 195.88 |
| + 1h + ATR stop 2x | 0.05 / 1.08 / 79.96 | 0.02 / 1.03 / 201.74 |
| + 1h + ATR stop 3x | 0.01 / 1.02 / 70.36 | -0.00 / 0.99 / 193.22 |

**Descartado, e dessa vez sem ambiguidade** — ao contrário do filtro de qualidade do candle
(que pelo menos tinha resultado misto), aqui o resultado é limpo e consistente nas duas
janelas: aumentar o múltiplo do ATR **piora monotonicamente** a expectância (1.5x > 2x > 3x
nas duas janelas), e o drawdown nem melhora de forma confiável (piora no 2x aos 180 dias). A
sugestão do livro (day traders usam múltiplo maior) simplesmente não se aplica a essa
estratégia/mercado — mesma lição do ADX: heurística de livro-texto não é garantia, quem decide
é o backtest. Parâmetro `atr_stop_multiplier` fica em `analysis/signals.py::generate_signal`
(default = produção) só pra permitir reexplorar no futuro, sem efeito nenhum na produção atual.

## Resultado do backtest: RSI com faixa por regime (2026-09-09)

Item 3 testado contra 60 e 180 dias reais, em cima da produção atual (filtro de 1h):

| Variante | 60d exp(R) / PF / maxDD(R) | 180d exp(R) / PF / maxDD(R) |
|---|---|---|
| + tendência 1h (produção atual) | 0.07 / 1.11 / 93.00 | 0.04 / 1.06 / 195.88 |
| + 1h + RSI faixa Constance Brown (40-90/10-60) | 0.06 / 1.09 / 97.00 | 0.04 / 1.06 / 168.83 |

**Descartado, resultado neutro** — nem a rejeição limpa do ATR (não piora monotonicamente),
nem a melhora clara que justificaria trocar a produção: levemente pior aos 60 dias, empatado
em expectância e PF aos 180 dias. Único ganho consistente foi redução de drawdown aos 180 dias
(mesmo padrão do filtro de qualidade do candle) — não o suficiente sozinho pra justificar a
mudança, dado o critério já estabelecido no projeto (precisa melhora consistente de
expectância nas duas janelas, não só redução de risco). Parâmetros `long_rsi_range`/
`short_rsi_range` ficam em `analysis/signals.py::generate_signal` (default = produção) só pra
reexplorar depois.

## Resultado do backtest: range por estrutura de preço (2026-09-09) — ADOTADO EM PRODUÇÃO

Item 4 testado em **3 janelas** (60, 180 e 365 dias) — precisou da terceira porque a amostra do
limiar 6x era pequena demais nas duas primeiras (56 e 231 sinais) pra confiar isoladamente:

| Variante | 60d | 180d | 365d |
|---|---|---|---|
| + 1h (produção anterior) | 0.07/1.11/93/2334sig | 0.04/1.06/196/6853sig | 0.03/1.05/207/13682sig |
| + 1h + range 4x | 0.03/1.04/75/1130sig | 0.02/1.02/121/3491sig | 0.01/1.02/167/6518sig |
| + 1h + range 6x | 0.10/1.17/9/**56**sig | 0.14/1.22/17/**231**sig | **0.15/1.22/15**/**371**sig |

*(formato: exp(R)/PF/maxDD(R)/nº sinais)*

**Adotado em produção** — ao contrário de todos os outros candidatos testados (que inverteram
ranking entre janelas ou ficaram neutros), o limiar 6x se manteve consistente e até melhorou
ligeiramente conforme a amostra cresceu (56→231→371 sinais, direção nunca inverteu). Expectância
~3-5x maior que a produção anterior, drawdown ~10-13x menor. Custo real, aceito conscientemente
pelo usuário: corta os sinais em ~97% (~37/dia → ~1/dia somando os 25 pares). 4x foi comparado e
descartado (mais fraco que 6x nas 3 janelas). Implementado em
`analysis/signals.py::confirms_price_structure_range` — não fica mais em `backtest/filters.py`
(mesmo tratamento que o filtro de 1h recebeu quando foi adotado).

## Revalidação sob o engine de backtest corrigido (2026-09-09, commit `b7272f6` de outra IA)

Outra ferramenta de IA (Codex) revisou `backtest/engine.py` depois da decisão acima e corrigiu
dois vieses de look-ahead que inflavam os números de todas as variantes, inclusive desta: (1) a
janela usada pra calcular o sinal incluía o próprio candle que tinha acabado de fechar — agora
para em `idx-1`; (2) a entrada passou a ser simulada na **abertura do candle seguinte**, não mais
no fechamento do candle de sinal, e só considera fechado um candle de timeframe maior (1h) que já
tenha `close_time_ms` no passado (antes bastava ter aberto). Também foi adicionado um modelo de
custo de execução (`ExecutionCosts`: taxa taker 0.04%/lado + slippage 0.02%/lado por padrão),
com o relatório agora separando R **bruto** (só slippage) de R **líquido** (também desconta
taxa+funding). Como a decisão de produção acima foi tomada contra o engine antigo (com viés e sem
custo), rerodamos as mesmas 3 janelas (60/180/365 dias) pra confirmar se ainda se sustenta:

| Janela | sinais (antes→depois) | win% | bruto(R) | líq(R) | PF líq | maxDD(R) |
|---|---|---|---|---|---|---|
| 60d | 56 → **7** | 57.1% | 0.61 | **0.17** | 1.24 | 3.78 |
| 180d | 231 → **28** | 64.3% | 0.87 | **0.65** | 2.34 | 3.78 |
| 365d | 371 → **55** | 49.1% | 0.43 | **0.24** | 1.39 | 11.31 |

**Continua adotado em produção.** A amostra caiu bastante (o engine corrigido é bem mais
rigoroso sobre o que conta como sinal executável — praticamente 8x menos sinais nas 3 janelas),
mas o R líquido (já descontando taxa+slippage) se manteve **positivo nas 3 janelas**, sem
inverter — mesmo critério usado pra adotar o filtro originalmente. Mais relevante ainda: rodando
as 12 variantes de `VARIANTS` sob este engine, o range 6x foi a **única** que ficou com R líquido
positivo nas 3 janelas — todas as outras (incluindo o filtro de 1h sozinho, que era a produção
anterior a este filtro) ficaram negativas em R líquido depois de descontar custo de execução
real. Ou seja, sob um padrão mais rigoroso e mais realista que o usado na decisão original, o
filtro se saiu melhor relativamente às alternativas, não pior — reforça a decisão em vez de
colocá-la em dúvida. Ressalva: `n=7` na janela de 60 dias é uma amostra pequena isoladamente;
o que sustenta a confiança é a consistência com as janelas maiores (28 e 55 sinais), igual ao
raciocínio já usado antes.

## Simulação de banca (2026-09-09) — "quanto eu teria hoje com R$100 há 1 ano?"

Pergunta do usuário, respondida com o R líquido **real de cada trade** (não a média) dos 55
sinais fechados pelo filtro de range 6x na janela de 365 dias (seção acima) — via
`net_r_multiple` de `backtest/report.py`, capitalizando o saldo trade a trade (script temporário
`backtest/equity_sim.py`, removido depois de extrair o resultado; o log completo por trade não
fica versionado, só o resumo abaixo).

| Risco por trade | R$100 há 1 ano viraria |
|---|---|
| 1% da banca | R$ 113,61 |
| 2% da banca | R$ 127,45 |
| 5% da banca | R$ 166,98 |

**O bot não define % de risco por trade** — isso é decisão de quem opera, não está no código
(nem em `config.py`), então qualquer número aqui depende de uma escolha externa ao backtest.
Ressalvas importantes, sem as quais o número é enganoso:

- É uma simulação **retroativa com a estratégia de hoje** — os dois filtros (1h e range 6x) só
  foram adotados em produção em 2026-09-09. Ninguém seguiu esses sinais ao vivo no ano passado;
  isso é "se a estratégia atual tivesse existido", não histórico real de operação.
- O limiar 6x foi escolhido **porque** performou bem nesses mesmos dados (`backtest/run.py`
  comparou 4x vs 6x e ficou com o melhor) — viés de seleção. Sample-size pequeno (55 trades)
  agrava isso.
- Juros compostos com fração fixa por trade supõe redimensionar a posição a cada operação
  conforme a banca cresce/encolhe — mecânica que o bot não executa (é só alerta).
- Custos assumidos (taxa 0.04%/lado, slippage 0.02%/lado, funding zero) são estimativas
  conservadoras, não a conta real de nenhuma corretora específica.
- Nenhum imposto, nenhuma falha de execução (ordem não preenchida no preço do modelo), nenhum
  saque/aporte no meio do caminho.

## Recomendação de próximos passos (nenhum implementado ainda)

1. ~~Filtro de qualidade do candle de sinal~~ — implementado e testado, **descartado**.
2. ~~Variantes de múltiplo de ATR pro stop~~ — implementado e testado, **descartado** (piora
   monotonicamente nas duas janelas, sem ambiguidade).
3. ~~RSI com faixa deslocada pelo regime de 1h já calculado~~ — implementado e testado,
   **descartado** (resultado neutro, sem melhora de expectância que se sustente).
4. ~~Detecção de trading range por estrutura de preço~~ — implementado e testado em 3 janelas,
   **adotado em produção** (ver seção acima).
5. **Divergência RSI/preço, stop ATR trailing, Donchian breakout, movimento medido como alvo** —
   mudanças de mecânica mais profundas (sinal novo ou saída dinâmica), maior esforço de
   implementação e validação; nenhum começado ainda.

**Balanço final (2026-09-09)**: 4 dos 5 candidatos testados via `backtest/run.py` contra até 3
janelas de histórico real. 3 descartados (ATR maior, qualidade do candle, RSI por regime); 1
**adotado em produção** (range por estrutura de preço) — junto com o filtro de 1h (já existente),
são as duas mudanças que sobreviveram ao processo de validação por backtest até agora. Resta só o
item 5 (mudanças de mecânica mais profundas) na lista, sem esforço iniciado.

Nenhuma dessas mudanças foi pro `analysis/signals.py`/`main.py` sem primeiro rodar como variant
no `backtest/run.py` contra histórico real — mesmo processo que decidiu o filtro de 1h e
descartou o ADX.
