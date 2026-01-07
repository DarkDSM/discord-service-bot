import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

# Charger les variables d'environnement
load_dotenv()

# Configuration du bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

@bot.event
async def on_ready():
    """Événement lorsque le bot est prêt"""
    print(f'✅ Bot connecté en tant que {bot.user}')
    print(f'📊 Servant {len(bot.guilds)} serveur(s)')
    print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')

@bot.event
async def on_command_error(ctx, error):
    """Gestion des erreurs de commandes"""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Vous n'avez pas la permission d'utiliser cette commande.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant: {error.param.name}", delete_after=10)
    else:
        print(f"❌ Erreur: {error}")
        await ctx.send(f"❌ Une erreur est survenue: {error}", delete_after=10)

async def load_cogs():
    """Charge tous les cogs"""
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and filename != '__init__.py':
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f'✅ Cog chargé: {filename[:-3]}')
            except Exception as e:
                print(f'❌ Erreur chargement {filename}: {e}')

async def main():
    """Fonction principale"""
    # Charger les cogs
    await load_cogs()
    
    # Démarrer le bot
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ ERREUR: DISCORD_TOKEN non trouvé dans .env")
        return
    
    await bot.start(token)

if __name__ == '__main__':
    asyncio.run(main())
