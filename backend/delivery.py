import discord
import asyncio

class ProductDeliverer:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.client = discord.Client(intents=discord.Intents.default())

        @self.client.event
        async def on_ready():
            print(f'Logado como {self.client.user}')

    async def send_product(self, user_id, product_details):
        await self.client.wait_until_ready()
        user = await self.client.fetch_user(user_id)
        if user:
            try:
                # Exemplo: enviando uma mensagem direta com os detalhes do produto
                await user.send(f"Olá! Seu produto foi entregue:\n\n{product_details}")
                print(f"Produto entregue para {user.name} ({user_id})")
                return True
            except discord.errors.Forbidden:
                print(f"Não foi possível enviar DM para {user.name} ({user_id}). Verifique as configurações de privacidade.")
                return False
        else:
            print(f"Usuário com ID {user_id} não encontrado.")
            return False

    async def start_bot(self):
        await self.client.start(self.bot_token)

    async def close_bot(self):
        await self.client.close()

# Exemplo de uso (será integrado ao bot Discord)
if __name__ == "__main__":
    # Substitua pelo token do seu bot Discord
    DISCORD_BOT_TOKEN = "SEU_TOKEN_AQUI"
    
    deliverer = ProductDeliverer(DISCORD_BOT_TOKEN)

    async def main():
        # Exemplo de como chamar a entrega de produto
        # await deliverer.send_product(123456789012345678, "Seu link de acesso: https://seusite.com/produto")
        
        # Para rodar o bot em background para entregas
        # await deliverer.start_bot()
        pass

    # asyncio.run(main())
    print("Este script deve ser executado como parte de um bot Discord maior.")
    print("Certifique-se de instalar a biblioteca discord.py: pip install discord.py")
