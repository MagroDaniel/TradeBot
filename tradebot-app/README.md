# TradeBot App: day trade automático com painel web (spot + futuros)

Evolução do `crypto-daytrade/`. Em vez de só mandar alerta no Telegram, este app **opera
sozinho** numa **conta demo** e mostra tudo num painel no navegador: saldo, posições, gráfico,
histórico completo (inclusive as perdas), log de cada decisão, parâmetros editáveis e um botão
de pânico.

> **Status (2026-10-26): Fases 0–2 do [PLANO.md](PLANO.md), com vários robôs simultâneos.** Só existe a conta demo local
> (preço real da Binance, dinheiro de mentira). Binance Demo Mode, o `.exe` e a conta real são
> as próximas fases. **Sem alavancagem, nunca**: spot só compra; futuros operam comprado e
> vendido a 1x.

## Rodar (Windows ou qualquer sistema com Python 3.11+)

```bash
cd tradebot-app
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

O navegador abre sozinho no painel. Os dados (banco, carteira demo, log) ficam em
`%APPDATA%\TradeBot` (Windows) ou `~/.tradebot`, fora da pasta do programa.

- **Fechar a aba não para o bot.** Isso é de propósito: as posições abertas continuam com stop e
  alvo monitorados. Para encerrar, use `Ctrl+C` na janela do terminal. Ao reabrir, o bot volta
  no mesmo estado (ligado ou pausado).
- Rodar `python app.py` de novo com o bot já aberto só abre o painel existente. Duas
  instâncias nunca operam a mesma carteira.

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
| `ema_cross` | EMA 9/21 + RSI + tendência do 1h + filtro de range (a do crypto-daytrade) | **Validada** em backtest (3 janelas, R líquido positivo) |
| `donchian_breakout` | Rompimento de canal + trailing, sem alvo fixo (tendência) | Candidata, falta rodar a pesquisa |
| `supertrend` | Virada do Supertrend com o 1h a favor | Candidata |
| `bollinger_reversion` | Reversão à média em mercado lateral (ADX baixo) | Candidata |
| `session_momentum` | Momentum intradiário de BTC/ETH (estudo acadêmico) | Candidata |

O porquê de cada uma e as fontes estão em [PLANO.md](PLANO.md#pesquisa-de-estratégias).

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

## Testes

```bash
pytest
```

São 83 testes, sem rede e sem credenciais. Um deles confere que a `ema_cross` gera
**exatamente** os mesmos sinais que a estratégia de produção do `crypto-daytrade`.
