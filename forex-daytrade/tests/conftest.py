"""Credenciais dummy pra permitir importar `config.py` (e o que depende dele, como
`news_watch.py`) durante os testes sem precisar de `.env` real — mesmo espírito do resto do
projeto (suíte roda sem rede/credencial real), só que aqui a dependência de `config.py` é
inevitável (`news_watch.py` importa `config` no nível do módulo, igual `main.py`). Só define
se a variável ainda não existir, pra não atropelar um `.env` real que porventura esteja
carregado (ex: rodando localmente com credenciais de verdade).
"""
import os

os.environ.setdefault("TWELVEDATA_API_KEY", "test-dummy-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-dummy-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "test-dummy-chat")
