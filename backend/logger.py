import discord
import asyncio
import datetime

class DiscordLogger:
    def __init__(self, bot_token, log_channel_id):
        self.bot_token = bot_token
        self.log_channel_id = log_channel_id
        self.client = discord.Client(intents=discord.Intents.default())
        self.log_channel = None

        @self.client.event
        async def on_ready():
            print(f'Logger bot logado como {self.client.user}')
            self.log_channel = self.client.get_channel(self.log_channel_id)
            if not self.log_channel:
                print(f"Canal de log com ID {self.log_channel_id} não encontrado.")

    async def log_event(self, event_type, message):
        if self.log_channel:
            embed = discord.Embed(
                title=f"[{event_type.upper()}] Novo Evento",
                description=message,
                color=discord.Color.blue(),
                timestamp=datetime.datetime.now()
            )
            await self.log_channel.send(embed=embed)
            print(f"Evento logado: {event_type} - {message}")
        else:
            print(f"[ERRO] Canal de log não configurado. Evento: {event_type} - {message}")

    async def start_bot(self):
        await self.client.start(self.bot_token)

    async def close_bot(self):
        await self.client.close()

# Exemplo de uso (será integrado ao bot Discord)
if __name__ == "__main__":
    # Substitua pelo token do seu bot Discord e ID do canal de logs
    DISCORD_BOT_TOKEN = "SEU_TOKEN_AQUI"
    LOG_CHANNEL_ID = 123456789012345678 # Substitua pelo ID do seu canal de logs
    
    logger = DiscordLogger(DISCORD_BOT_TOKEN, LOG_CHANNEL_ID)

    async def main():
        # Para rodar o bot em background para logs
        # await logger.start_bot()
        
        # Exemplo de log de evento
        # await logger.log_event("VENDA", "João Silva comprou Curso Premium (R$ 99.90)")
        pass

    # asyncio.run(main())
    print("Este script deve ser executado como parte de um bot Discord maior.")
    print("Certifique-se de instalar a biblioteca discord.py: pip install discord.py")
