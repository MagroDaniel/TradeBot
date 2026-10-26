# Changelog

Cada versão publicada tem uma seção `## vX.Y.Z`; o texto dela vira a página da release e as
notas que aparecem no botão "Atualizar" do painel.

## v0.1.0

Primeira versão do TradeBot como aplicativo do Windows.

- Painel no navegador com vários robôs ao mesmo tempo, cada um com estratégia, parâmetros e carteira demo próprios, e a Visão geral comparando todos.
- Conta demo local para spot e futuros, com preços e livro de ofertas reais da Binance e sempre sem alavancagem.
- Proteções: kill switch, PARAR TUDO, perda máxima no dia, pausa depois de stops seguidos, espera antes de reentrar no mesmo par e drawdown máximo.
- Copy trading de carteiras da Hyperliquid, com ranking, análise da carteira e acompanhamento de aumentos e reduções.
- Pesquisa de estratégias com backtest (`python -m tradebot.research`).
- Ícone na bandeja do Windows e atualização pelo botão no painel.

Aviso: nenhuma estratégia está aprovada no backtest com custos reais (veja o PLANO.md). Use na conta demo.
