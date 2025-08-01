# pip install discord.py
import discord

import aiohttp
from chzzkpy.unofficial.chat import ChatClient, ChatMessage


# Configuration
channel_id = "channel_id"

# Discord Setting
webhook_url = "discord_webhook_url"


chzzk_client = ChatClient(channel_id)
discord_client = discord.Webhook.from_url(
    url=webhook_url, session=aiohttp.ClientSession()
)


@chzzk_client.event
async def on_connect():
    print("Ready bot.")


@chzzk_client.event
async def on_chat(message: ChatMessage):
    profile = message.profile
    await discord_client.send(
        username=profile.nickname,
        avatar_url=profile.profile_image_url or discord.utils.MISSING,
        content=message.content,
    )


chzzk_client.run()
