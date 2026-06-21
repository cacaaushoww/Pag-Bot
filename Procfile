# Roda a API com gunicorn (servidor de produção) em vez do
# `app.run()` de desenvolvimento.
#
# IMPORTANTE: como o bot do Discord (asyncio) hoje roda dentro do
# mesmo processo Python que serve o Flask, só é seguro usar 1 worker
# aqui — múltiplos workers significariam múltiplas conexões do MESMO
# bot ao Discord (gateway duplicado), o que o Discord rejeita/quebra.
#
# O --threads aumenta a concorrência de requisições HTTP dentro
# desse único worker (ajuda quando uma rota espera o bot responder
# via run_coroutine_threadsafe), mas não substitui rodar bot e API
# em processos/serviços separados. Veja SCALING.md para o próximo passo.
web: gunicorn -w 1 --threads 8 --timeout 60 -b 0.0.0.0:$PORT backend.bot:app
