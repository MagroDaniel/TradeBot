# Plano: TradeBot App

Objetivo: tirar o bot do Telegram e ter um **app de Windows com painel web** que opera day
trade sozinho em **spot e futuros** da Binance, começando por **conta demo** para testar e
ajustar parâmetros. Plano montado em 2026-10-26 depois de analisar Hummingbot, Vibe-Trading,
Freqtrade, Jesse, OctoBot e Nautilus Trader.

## Decisões tomadas

- **Sistema próprio**, sem adotar um framework inteiro. As ideias vêm dos repositórios
  analisados; o código é nosso, e nada de GPL foi copiado.
- **Spot + futuros**, cada um com sua carteira demo. **Sem alavancagem**: spot só compra,
  futuros a 1x.
- **Navegador + processo em segundo plano**, em vez de janela própria (ver "Janela ou
  navegador" abaixo).
- **Nenhuma estratégia nova vai para uso sem passar pela pesquisa**: R positivo em todas as
  fatias do período.

## Fases

- [x] **Fase 0 (fundação)**: núcleo em `tradebot/`; `ema_cross` portada com teste de paridade
      contra o crypto-daytrade; SQLite no lugar do JSON; contrato de broker.
- [x] **Fase 1 (motor + demo local)**:
  - `PaperBroker` com preenchimento pelo livro de ofertas real;
  - triple barrier com trailing;
  - portão de risco, proteções e kill switch;
  - estado que sobrevive a reinício;
  - log de auditoria.
- [x] **Fase 2 (painel web)**:
  - dashboard: status, patrimônio, posições, histórico e log;
  - gráfico por posição;
  - configurações completas;
  - token de acesso por execução;
  - JS embutido (funciona sem CDN).
- [x] **Vários robôs simultâneos** (pedido em 2026-10-26): uma aba por robô, cada um com
      estratégia, parâmetros e carteira demo próprios; visão geral comparando todos.
- [x] **Copy trading** (pedido em 2026-10-26): robô "Copiar carteira" seguindo traders da
      Hyperliquid (posições públicas on-chain), com ranking e análise de carteira no painel.
      Executa nos futuros da Binance a 1x, com stop próprio. Acompanha aumentos e reduções
      parciais do trader. Pendente: medir o atraso real da cópia na demo.
- [~] **Fase 4 antecipada (pesquisa)**:
  - [x] backtester genérico com as mesmas regras de saída do motor;
  - [x] 4 estratégias candidatas;
  - [x] bootstrap e fatias de consistência;
  - [x] download de `data.binance.vision`;
  - [x] rodar contra dados reais (12 meses): **nenhuma aprovada**, ver seção abaixo.
  - [ ] backtest pelo painel.
- [ ] **Fase 3 (Binance Demo Mode)**: broker que manda ordens de verdade para a conta demo
      oficial (`demo-api.binance.com` no spot, testnet/demo de futuros). Inclui:
  - chaves guardadas criptografadas (`keyring` / cofre do Windows);
  - **stop também na corretora** como rede de segurança;
  - reconciliação ao abrir (posições da corretora × banco local).
- [x] **Fase 5 (executável)**: `TradeBot.exe` (PyInstaller, arquivo único) gerado pelo
      GitHub a cada tag de versão, com autoteste antes de publicar; ícone na bandeja (abrir
      painel / sair); atualização pelo painel (baixa da release, confere o SHA-256, troca e
      reabre). Pendente: iniciar com o Windows (opcional) e assinatura digital do `.exe` (evita
      o aviso do SmartScreen; certificado pago).
- [ ] **Fase 6 (conta real, só depois)**:
  - critério definido **antes**: X semanas de demo, N trades, resultado dentro da faixa do
    backtest;
  - chave sem permissão de saque e com whitelist de IP;
  - limites pequenos no começo.

## Janela ou navegador: decidido navegador + segundo plano

Um bot de trading precisa continuar rodando quando você fecha a tela. Com janela própria
(pywebview), fechar a janela é fechar o programa, e as posições abertas ficariam sem stop
monitorado. Contornar isso exige esconder a janela na bandeja, o que dá na mesma que o
navegador, só que com mais código e mais coisa para quebrar.

Por isso:
- o bot roda como processo em segundo plano;
- o painel abre no navegador e pode ser fechado e reaberto à vontade;
- na Fase 5 entra o **ícone na bandeja do Windows** (perto do relógio) para abrir o painel ou
  sair.

Bônus: dá para acompanhar o bot pelo navegador do celular na mesma rede no futuro, se você
quiser (hoje ele só aceita conexões do próprio PC, por segurança).

## Pesquisa de estratégias

**Ponto de partida honesto.** A `ema_cross` atual tem R líquido positivo, mas pequeno, e gera
cerca de 1 sinal por dia somando 25 pares. Na revalidação com custos foram 55 sinais em 365
dias, +0,24R por trade. Os testes anteriores (crypto-daytrade) já descartaram:
- ADX como filtro;
- stop por ATR maior;
- RSI por regime;
- qualidade do candle de sinal;
- aumentar para 50 pares.

As candidatas abaixo atacam o que **ainda não foi testado**:

1. **Saída dinâmica em vez de alvo fixo 2R** (`donchian_breakout`, `supertrend` e o
   `trailing_atr` da `ema_cross`).
   - Retornos de cripto têm cauda gorda: poucos trades enormes pagam o resto.
   - Alvo fixo corta exatamente esses trades. Estratégias de tendência ganham com acerto baixo
     (30–40%) e ganho médio grande.
   - Fonte: rompimento Donchian com stop ATR em BTC, positivo mas sensível a custo e parâmetro
     ([Poluri, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6272239)). Daí o
     timeframe de 1h como padrão (menos trades, menos custo) e o filtro de média longa.
2. **Reversão à média em mercado lateral** (`bollinger_reversion`).
   - É o oposto da `ema_cross`: lucra no "chop" que faz o cruzamento de médias dar
     whipsaw.
   - Base: controllers `bollinger_v1`/`dman_v3` do Hummingbot, mais RSI extremo e filtro de
     regime por ADX baixo.
   - Na pesquisa do forex isso apareceu como provável caminho (mercado em range 70–80% do
     tempo). Aqui é o primeiro teste em cripto.
3. **Supertrend com confirmação do 1h** (`supertrend`).
   - Base: controller `supertrend_v1` do Hummingbot.
   - Reaproveita a lição do crypto-daytrade de que o sinal de 15m sem o 1h a favor tem
     expectância negativa.
4. **Momentum intradiário de sessão** (`session_momentum`).
   - Shen, Urquhart & Wang (2022,
     [Financial Review](https://onlinelibrary.wiley.com/doi/abs/10.1111/fire.12290)): em
     Bitcoin, o retorno do início do dia prevê o do fim, mais forte nas sessões de maior
     volume.
   - Adaptação: o retorno de 00h–14h UTC define a direção, com saída às 21h UTC.
   - Só BTC/ETH. É um único estudo, sem replicação independente com custos.
5. **Sazonalidade por horário (ainda não implementada)**.
   - Há estudos de retorno concentrado em certas horas
     ([QuantPedia](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/),
     [turn-of-the-candle](https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/)).
   - Risco alto de overfitting. Se entrar, será como **filtro de horário** testado fora da
     amostra, não como estratégia.

**Ideias para depois:**
- filtro de funding rate em futuros (não abrir long com funding muito positivo);
- combinar estratégias por regime: ADX alto → tendência, ADX baixo → reversão. Só depois que
  cada uma, isolada, se provar.

**Processo para cada candidata:**
1. `python -m tradebot.research` em 365 e 540 dias, spot e futuros.
2. Só seguem as com R positivo em todas as fatias e p < 0,10.
3. Variar 1–2 parâmetros em torno do default. Se só um valor exato funciona, é overfitting.
4. As aprovadas vão para **semanas de conta demo** ao lado da `ema_cross`, comparando o
   resultado real com o backtest do mesmo período.

## Resultado da pesquisa (2026-10-26): nenhuma aprovada

`python -m tradebot.research --source archive --months 12 --market futures --market spot`.
Período: out/2025 a set/2026. 15 pares líquidos fixos. Custos por lado: futuros 0,05% de taxa
+ 0,02% de slippage; spot 0,10% + 0,02%.

| estratégia | mercado | trades | acerto | R bruto | R líquido | R por fatia (líq.) | p |
|---|---|---|---|---|---|---|---|
| ema_cross (produção) | futuros | 86 | 43% | **+0,22** | −0,01 | −0,17 / −0,26 / +0,37 | 0,53 |
| ema_cross (produção) | spot | 54 | 44% | **+0,29** | −0,14 | −0,35 / −0,17 / −0,00 | 0,73 |
| donchian_breakout | futuros | 1103 | 33% | −0,04 | −0,11 | −0,22 / −0,05 / −0,08 | 0,99 |
| donchian_breakout | spot | 617 | 31% | +0,03 | −0,14 | −0,35 / +0,02 / −0,12 | 0,98 |
| supertrend | futuros | 1441 | 29% | +0,03 | −0,07 | −0,07 / −0,05 / −0,10 | 0,95 |
| supertrend | spot | 805 | 26% | +0,03 | −0,18 | −0,27 / −0,14 / −0,12 | 1,00 |
| bollinger_reversion | futuros | 1239 | 31% | −0,13 | −0,35 | −0,38 / −0,31 / −0,35 | 1,00 |
| bollinger_reversion | spot | 569 | 29% | −0,17 | −0,58 | −0,61 / −0,60 / −0,53 | 1,00 |
| session_momentum | futuros | 1105 | 35% | −0,12 | −0,19 | −0,30 / −0,13 / −0,11 | 1,00 |
| session_momentum | spot | 598 | 35% | −0,05 | −0,19 | −0,37 / −0,05 / −0,11 | 1,00 |

**Leitura:**
- **A `ema_cross` é a única com vantagem antes do custo** (+0,22R / +0,29R por trade). O
  problema é o custo: com o stop curto do 15m (1,5× ATR), taxa + slippage custam ~0,22R por
  trade em futuros e ~0,43R no spot, e engolem a vantagem. A revalidação antiga do
  crypto-daytrade (+0,24R líquido) usava 25 pares (o top de hoje aplicado ao passado), taxa de
  0,04% e outro período.
- **Mais tempo de gráfico não resolve**: em 30m/2h e 1h/4h, o filtro de range deixa poucos
  sinais (29 e 16 em futuros) e o resultado bruto também fica negativo.
- **Donchian, Supertrend e momentum de sessão** não têm vantagem nem antes do custo. Isso
  contraria o que a literatura sugeria para este período e universo.
- **Bollinger lateral** é claramente perdedora: em cripto, "comprar a queda" no 15m com ADX
  baixo pega mais faca caindo do que reversão.

**Próximos testes que fazem sentido (atacam o custo, onde está o problema):**
1. **Entrada com ordem limitada (maker)**: em futuros a taxa maker é 0,02% contra 0,05% de
   taker, e não há slippage na entrada. Isso corta ~40% do custo da `ema_cross`, mas exige
   simular ordem que pode não ser executada (sem fill = sem trade).
2. **Desconto de taxa com BNB / nível VIP**: só muda o número, não a estratégia. Vale medir
   com a taxa real da sua conta.
3. **Janela maior (24 meses) e 25 pares**, para ver se a vantagem bruta da `ema_cross` se
   mantém ou foi do período.
4. Só depois disso voltar a mexer em sinal. Regra mantida: nada vira "validada" sem R líquido
   positivo em todas as fatias.

## Ideias aproveitadas de cada repositório

| De onde | O quê | Onde está |
|---|---|---|
| Hummingbot | Triple barrier (stop/alvo/tempo/trailing); separar estratégia de execução; controllers Bollinger/Supertrend | `position.py`, `strategies/` |
| Vibe-Trading | Kill switch por arquivo; portão de risco fail-closed; log de auditoria; servidor só em 127.0.0.1 com token; demo e real separados | `risk.py`, `store.py`, `web/server.py`, `app.py` |
| Freqtrade | Dry-run preenchendo pelo livro de ofertas; proteções (StoplossGuard, MaxDrawdown, Cooldown); "parar novas entradas"; forçar saída | `brokers.py`, `risk.py`, `engine.py` |
| Jesse | Teste de significância por bootstrap em blocos | `backtest.py::bootstrap_p_value` |
| Nautilus | Mesma lógica no backtest e ao vivo | `position.evaluate_bar` usado pelos dois |
| OctoBot | Viabilidade do `.exe` com PyInstaller para bot Python grande | Fase 5 |
