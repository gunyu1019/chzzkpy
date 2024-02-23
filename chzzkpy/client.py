import asyncio

from typing import Optional
from .http import ChzzkAPISession, NaverGameAPISession
from .live_status import LiveStatus, LiveDetail
from .user import User


class Client:
    def __init__(
            self,
            loop: Optional[asyncio.AbstractEventLoop] = None,
            authorization_key: Optional[str] = None,
            session_key: Optional[str] = None
    ):
        self.loop = loop or asyncio.get_event_loop()
        self._api_session = ChzzkAPISession(loop=loop)
        self._game_session = NaverGameAPISession(loop=loop)

        if authorization_key is not None and session_key is not None:
            self.login(authorization_key, session_key)

    async def close(self):
        await self._api_session.close()
        await self._game_session.close()
        return

    def login(self, authorization_key: str, session_key: str):
        self._api_session.login(authorization_key, session_key)
        self._game_session.login(authorization_key, session_key)

    async def live_status(self, channel_id: str) -> LiveStatus:
        res = await self._api_session.live_status(channel_id=channel_id)
        return res.content

    async def live_detail(self, channel_id: str) -> LiveDetail:
        res = await self._api_session.live_detail(channel_id=channel_id)
        return res.content

    async def user(self) -> User:
        res = await self._game_session.user()
        return res.content