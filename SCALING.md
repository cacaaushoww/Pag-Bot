# Escalabilidade — o que foi feito agora e o que falta

## O que mudou aqui
- `app.run()` (servidor de desenvolvimento do Flask, single-thread,
  não pensado pra produção) foi substituído por **gunicorn** no
  `Procfile`, com `--threads 8` pra aguentar várias requisições HTTP
  concorrentes dentro do mesmo processo.
- O bot do Discord continua rodando numa thread em background do
  mesmo processo — isso não mudou, e por enquanto é uma limitação
  conhecida, não um bug: dividir agora custaria mais do que vale para
  o tamanho atual do projeto.

## A limitação que continua existindo
Bot (asyncio) e API (Flask) compartilham processo. Isso significa:
- **Só pode haver 1 worker do gunicorn.** Cada worker tentaria abrir
  sua própria conexão do bot ao gateway do Discord — o Discord não
  permite múltiplas sessões do mesmo bot token simultâneas de forma
  saudável.
- Se o processo cair, cai bot e API juntos.
- Rotas que dependem do bot responder (ex: `/api/bot-name` POST, que
  muda o nick no Discord) bloqueiam uma thread do Flask esperando o
  loop assíncrono do bot — sob carga alta isso enfileira.

## Quando isso vira um problema de verdade
Quando o painel tiver uso simultâneo relevante (vários admins
diferentes, vários servidores ativos ao mesmo tempo) ou quando o bot
precisar reiniciar/escalar independente da API.

## Caminho recomendado, em ordem
1. **Curto prazo (já feito):** gunicorn com 1 worker + threads, em vez
   do servidor de dev.
2. **Médio prazo:** separar em dois serviços/processos:
   - Serviço A: só o bot do Discord, escreve tudo no Supabase.
   - Serviço B: só a API Flask/FastAPI, lê/escreve no Supabase
     diretamente. As poucas operações que *precisam* falar com o bot
     em tempo real (trocar nick, listar canais) passam a usar uma
     fila simples (ex: Supabase Realtime, ou uma tabela de
     "comandos pendentes" que o bot consome) em vez de uma chamada
     bloqueante direta.
   - Isso permite escalar a API com múltiplos workers livremente,
     porque ela não tem mais um bot Discord vivendo dentro dela.
3. **Se quiser ficar 100% assíncrono nativo:** migrar a API de
   Flask para **FastAPI**, rodando no mesmo event loop do
   `discord.py`. Elimina a ponte thread-to-asyncio
   (`run_coroutine_threadsafe`) por completo, mas é uma reescrita
   maior — vale a pena só quando o passo 2 não for suficiente.
