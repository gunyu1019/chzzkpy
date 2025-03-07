# required spotipy
# pip install spotipy
import spotipy
import asyncio
from typing import Any
from pydantic import BaseModel

from chzzkpy.offical import Client, Message, UserPermission

# Configuration
prefix = "$"

# Naver Authorization
client_id = "client_id"
client_secret = "client_secret"


# Spotify Authorization
client_id = "Spotify App Client ID"
secret = "Spotify App Client Secrect ID"
redirect_uri = "http://localhost:8888/redirect"
scope = "user-modify-playback-state"
oauth_manager = spotipy.SpotifyOAuth(
    client_id=client_id, client_secret=secret, redirect_uri=redirect_uri, scope=scope
)

oauth_manager.get_auth_response()

chzzk_client = Client(client_id, client_secret)
spotify_client = spotipy.Spotify(oauth_manager=oauth_manager)


class SpotifyMusicInfo(BaseModel):
    name: str
    artists: str
    uri: str

    @classmethod
    def from_spotify(cls, data: dict[str, Any]):
        artists = ", ".join([x["name"] for x in data["artists"]])
        return cls(name=data["name"], artists=artists, uri=data["uri"])


@chzzk_client.event
async def on_connect(_):
    print("Ready bot.")


@chzzk_client.event
async def on_chat(message: Message):
    if not message.content.startswith("%s선곡" % prefix):
        return

    music_name = message.content.split()[1:]
    search_result = spotify_client.search(q=music_name, type="track", limit=5)
    tracks_result = search_result["tracks"]
    items = [SpotifyMusicInfo.from_spotify(x) for x in tracks_result["items"]]

    if len(items) <= 0:
        await message.send("검색 결과가 없습니다 :(")
        return
    item = items[0]
    spotify_client.add_to_queue(item.uri)
    await message.send("%s - %s 노래가 추가되었습니다." % (item.name, item.artists))
    return


async def main():
    authorization_url = chzzk_client.generate_authorization_token_url(
        redirect_url="https://localhost", state="abcd12345"
    )
    print(f"Please login with this url: {authorization_url}")
    code = input("Please input response code: ")

    user_client = await chzzk_client.generate_user_client(code, "abcd12345")
    await user_client.connect(UserPermission(chat=True))


asyncio.run(main())
