import os
from dotenv import load_dotenv

from apocalypse_bot.core.rate_limit_guard import install_stream_guard, make_log_handler

# Install before discord.py configures logging so giant Cloudflare HTML responses
# are compacted even when they arrive through stderr.
install_stream_guard()

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
from apocalypse_bot.core.bot import bot

if not TOKEN:
    raise RuntimeError("Discord bot token environment variable is missing (DISCORD_TOKEN/BOT_TOKEN/TOKEN).")

bot.run(TOKEN, log_handler=make_log_handler())
