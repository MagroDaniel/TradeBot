# TradeBot: day trade automático com painel web (spot + futuros)

Evolução do antigo bot de alertas `crypto-daytrade` (removido do repositório em 2026-10 junto
com os bots de apostas e forex; continuam no histórico do Git, último commit com eles:
`d360252`). Em vez de só mandar alerta no Telegram, este app **opera
sozinho** numa **conta demo** e mostra tudo num painel no navegador: saldo, posições, gráfico,
histórico completo (inclusive as perdas), log de cada decisão, parâmetros editáveis e um botão
de pânico.

> **Status (2026-10-26): Fases 0–2 e 5 do [PLANO.md](PLANO.md) (com vários robôs, copy trading e o `.exe` com atualização pelo painel).** Só existe a conta demo local
> (preço real da Binance, dinheiro de mentira). Binance Demo Mode, o `.exe` e a conta real são
> as próximas fases. **Sem alavancagem, nunca**: spot só compra; futuros operam comprado e
> vendido a 1x.

## Instalar (Windows)

1. Baixe o `TradeBot.exe` da [última release](https://github.com/MagroDaniel/TradeBot/releases/latest).
2. Coloque numa pasta sua (ex: `Documentos\TradeBot`) e dê dois cliques.
   - Na primeira vez o Windows pode mostrar **"O Windows protegeu o computador"**: o executável
     ainda não tem assinatura digital paga. Clique em **Mais informações → Executar assim mesmo**.
     Se quiser conferir o arquivo, o SHA-256 dele está no `TradeBot.exe.sha256` da mesma release.
3. O painel abre no navegador e aparece um **ícone perto do relógio** (Abrir painel / Sair).

Funcionamento:
- **Fechar a aba não para o bot.** As posições abertas continuam com stop e alvo monitorados.
  Para encerrar, use **Sair** no ícone da bandeja. Ao reabrir, cada robô volta no mesmo estado.
- Abrir o `.exe` de novo com ele já aberto só abre o painel existente. Duas instâncias nunca
  operam as mesmas carteiras.
- Os dados (robôs, carteiras demo, histórico, log) ficam em `%APPDATA%\TradeBot`, fora do
  executável. Trocar ou apagar o `.exe` não apaga nada.
- **Atualizações**: quando sai uma release nova, aparece uma faixa no topo do painel com as
  notas e o botão **Atualizar**. Ele baixa o executável novo, confere o SHA-256, fecha o
  TradeBot, troca o arquivo e reabre sozinho (uns 20 segundos; se houver posição aberta, ele
  avisa antes). Também dá para procurar manualmente em ⚙ → Versão.

## Rodar pelo código-fonte (desenvolvimento)

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

O navegador abre sozinho no painel. Sem ícone na bandeja fora do Windows; encerre com `Ctrl+C`.

## O painel: vários robôs ao mesmo tempo

Cada **robô** roda uma estratégia, com parâmetros, pares, risco, proteções e **carteira demo
próprios**. Robôs nunca dividem saldo nem vaga de posição, então dá para comparar
estratégias (ou duas versões da mesma, ex: alvo fixo × trailing) lado a lado de forma justa.

- **Visão geral**: tabela comparando todos os robôs (patrimônio, retorno, resultado,
  operações, acerto, R médio, posições abertas) e o gráfico de retorno % de cada um.
- **Uma aba por robô**: status e botões, carteira spot/futuros, gráfico de patrimônio,
  posições abertas, histórico completo e log de decisões. As configurações do robô ficam no
  link "configurações" da aba.
- **+ Novo robô**: escolhe a estratégia e, opcionalmente, copia mercados, pares, risco e
  proteções de outro robô. A estratégia de um robô é fixa; para testar outra, crie outro robô.
  Até 10 robôs.

| Controle | O que faz |
|---|---|
| **▶ Ligar** (por robô) | Começa a operar. Só entra a partir do **próximo** candle fechado, nunca num sinal antigo |
| **⏸ Parar novas entradas** (por robô) | Continua cuidando das posições abertas (stop, alvo, trailing), mas não abre novas |
| **■ Desligar** (por robô) | Para o robô. Avisa se houver posição aberta, porque ela fica sem stop monitorado |
| **⛔ PARAR TUDO** (topo, global) | Fecha todas as posições de **todos** os robôs a mercado e aciona o kill switch |
| **Fechar** (por posição) | Fecha uma posição a mercado |
| **Resetar carteira demo** | Volta ao saldo inicial e apaga o histórico daquele robô naquele mercado |
| **⚙** (topo) | Configurações gerais (intervalo do ciclo) |

Clicar no par abre o gráfico de candles com entrada, stop (atual e inicial), alvo e saída.

O motor busca preços e candles **uma vez por ciclo** e compartilha entre os robôs, então ter
vários ligados não multiplica as chamadas à Binance.

## Copy trading (copiar um trader)

A aba **Copiar trader** mostra o ranking público da [Hyperliquid](https://app.hyperliquid.xyz/leaderboard)
(corretora de futuros on-chain onde as posições de qualquer carteira são públicas) e analisa
qualquer carteira antes de você copiar:
- lucro total e do mês;
- pior queda;
- alavancagem atual;
- acerto dos fechamentos recentes;
- frequência de operação;
- posições abertas agora.

A análise também mostra alertas, por exemplo "opera demais, a cópia vai chegar atrasada".

De lá você cria um robô **Copiar carteira**. Ele aparece como qualquer outro robô (aba própria,
carteira demo, comparação na Visão geral) e:
- quando o trader **abre** uma moeda nova, abre a mesma direção nos futuros da Binance;
- quando o trader **fecha ou inverte**, fecha (e abre o lado novo, se ele inverteu);
- quando o trader **aumenta ou reduz** a posição em mais de 10% (ajustável), faz o mesmo na
  mesma proporção. Cada redução vira uma linha própria no histórico, com o resultado daquela
  parte; o aumento recalcula o preço médio e o stop e respeita o tamanho máximo da posição;
- **não copia** o que ele já tinha aberto quando você ligou o robô (opcional nas
  configurações);
- usa a **fatia da carteira dele, sem a alavancagem dele**: se ele está a 5x, tudo é reduzido
  para caber em 1x do seu saldo (padrão: até 90% do patrimônio do robô);
- tem **stop próprio** (padrão 5%), porque não dá para ver o stop dele. Se o stop bater, só volta
  a copiar aquela moeda quando ele fechar e reabrir;
- se a Hyperliquid não responder, **não fecha nada**: mantém as posições com o stop próprio;
- passa pelo mesmo portão de risco dos outros robôs (limites, proteções, PARAR TUDO).

Moedas sem par nos futuros da Binance são puladas (e avisadas no log). Reduções parciais
contam como operações separadas no histórico e nas estatísticas do robô.

## Como o bot decide e se protege

1. **Estratégia**: só diz "entrar aqui, stop ali, alvo lá". Rodam sobre candles **fechados**.
2. **Portão de risco** (`tradebot/risk.py`): toda entrada passa por aqui e, na dúvida, é negada.
   Ele checa:
   - **kill switch**: o arquivo `HALT` na pasta de dados. Se existir, nada entra; dá até para
     criar na mão;
   - **limites**: no spot só compra; uma posição por par; máximo de posições no total e na
     mesma direção; máximo de operações por dia;
   - **proteções**:
     - perda máxima no dia;
     - N stops seguidos pausam as entradas por um tempo;
     - espera antes de reentrar no mesmo par;
     - drawdown máximo desde o pico (pausa até você liberar no painel).
3. **Tamanho da posição**: bater o stop custa X% do patrimônio (padrão 1%), limitado pelo teto
   de tamanho e pelo caixa (sem alavancagem).
4. **Execução demo** (`tradebot/brokers.py`): a ordem a mercado "come" o livro de ofertas real
   da Binance nível a nível e paga a taxa taker. Se o slippage estimado passar do máximo
   configurado, a entrada é recusada.
5. **Saída** (`tradebot/position.py`): stop, alvo, tempo-limite e trailing stop, conferidos a
   cada ciclo (10 s). Saída por sinal da estratégia (ex: Supertrend virou) é checada no
   fechamento de cada candle.

Tudo vai para o **log de decisões**: sinal, entrada negada (e por quê), abertura, trailing,
fechamento, proteção ativada.

## Estratégias

| Estratégia | Ideia | Status |
|---|---|---|
| `ema_cross` | EMA 9/21 + RSI + tendência do 1h + filtro de range (a do crypto-daytrade) | Reprovada em 2026-10 (vantagem antes das taxas, mas o custo consome tudo) |
| `donchian_breakout` | Rompimento de canal + trailing, sem alvo fixo (tendência) | Reprovada |
| `supertrend` | Virada do Supertrend com o 1h a favor | Reprovada |
| `bollinger_reversion` | Reversão à média em mercado lateral (ADX baixo) | Reprovada (a pior) |
| `session_momentum` | Momentum intradiário de BTC/ETH (estudo acadêmico) | Reprovada |
| `copy_wallet` | Copia as aberturas/fechamentos de um trader da Hyperliquid | Sem backtest; avalie pela análise da carteira e pela demo |

**Nenhuma estratégia tem vantagem comprovada hoje.** Na pesquisa de 2026-10-26 (12 meses, 15 pares, spot e futuros, com taxas e slippage) todas ficaram negativas. Use os robôs para experimentar na conta demo, não como fonte de lucro. Números, causas e próximos testes em [PLANO.md](PLANO.md#resultado-da-pesquisa-2026-10-26-nenhuma-aprovada).

## Pesquisa de estratégias (backtest)

```bash
python -m tradebot.research                                    # todas, futuros, 365 dias
python -m tradebot.research --market spot --market futures --days 540
python -m tradebot.research --strategy donchian_breakout --set entry_channel=55 --set trailing_atr=4
python -m tradebot.research --source archive --months 24       # baixa de data.binance.vision (mais rápido)
```

O comando imprime uma tabela por estratégia com:
- número de trades, acerto e R médio líquido (já descontando taxa e slippage);
- profit factor e drawdown;
- **R médio em cada fatia do período** (`--parts`, padrão 3);
- **p do bootstrap** (chance de o resultado ser sorte);
- quanto US$1000 virariam arriscando 1% por trade.

O veredito "CANDIDATA" só aparece com R positivo **em todas as fatias** e p < 0,10. Esse é o
mesmo critério que o crypto-daytrade usou para adotar ou descartar filtros. O backtest usa as
mesmas regras de saída do bot ao vivo e entra na abertura do candle seguinte ao sinal.

## Testes e publicação de versão

```bash
pytest
```

Os testes também rodam no GitHub a cada push (`.github/workflows/tests.yml`).

Para publicar uma versão nova do `.exe`:
1. Suba `__version__` em `tradebot/__init__.py` (ex: `0.2.0`).
2. Escreva a seção `## v0.2.0` no `CHANGELOG.md`.
3. Faça commit e envie a tag: `git tag v0.2.0 && git push origin v0.2.0`.

O GitHub (`.github/workflows/release.yml`) roda os testes num Windows, gera o `TradeBot.exe`
com o PyInstaller (`TradeBot.spec`), faz o autoteste do executável e publica a release com o
`.exe` e o SHA-256. Os painéis já instalados mostram o botão **Atualizar** em até 6 horas.

São 112 testes, sem rede e sem credenciais. A paridade da `ema_cross` com a estratégia do
antigo `crypto-daytrade` (sinal por sinal) foi verificada enquanto os dois estavam no repositório.
