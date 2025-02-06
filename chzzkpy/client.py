"""MIT License

Copyright (c) 2024 gunyu1019

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import asyncio

from typing import Optional, TYPE_CHECKING
from .http import ChzzkAPISession, NaverGameAPISession
from .live import Live, LiveStatus, LiveDetail
from .user import User
from .video import Video
from .manage.manage_client import ManageClient


if TYPE_CHECKING:
    from .channel import Channel
    from types import TracebackType
    from typing_extensions import Self


class Client:
    """Represents a client to connect Chzzk (Naver Live Streaming)."""

    def __init__(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        authorization_key: Optional[str] = None,
        session_key: Optional[str] = None,
    ):
        self.loop = loop or asyncio.get_event_loop()
        self._closed = False
        self._api_session = None
        self._game_session = None

        if authorization_key is not None and session_key is not None:
            self.login(authorization_key, session_key)

        self._session_initial_set()

        # For management feature
        self._manage_client: dict[str, ManageClient] = dict()
        self._latest_manage_client_id = None

    def _session_initial_set(self):
        self._api_session = ChzzkAPISession(loop=self.loop)
        self._game_session = NaverGameAPISession(loop=self.loop)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if not self.is_closed:
            await self.close()

    @property
    def is_closed(self) -> bool:
        """Indicates if the session is closed."""
        return self._closed

    async def close(self):
        """Closes the connection to chzzk."""
        self._closed = True
        await self._api_session.close()
        await self._game_session.close()

        for manage_client in self._manage_client.values():
            if manage_client.is_closed:
                continue

            await manage_client.close()
        return

    def login(self, authorization_key: str, session_key: str):
        """Login at Chzzk.
        Used for features that require a login. (ex. user method)

        Parameters
        ----------
        authorization_key : str
            A `NID_AUT` value in the cookie.
        session_key : str
            A `NID_SES` value in the cookie.
        """
        self._api_session.login(authorization_key, session_key)
        self._game_session.login(authorization_key, session_key)

    @property
    def has_login(self) -> bool:
        return all((self._api_session.has_login, self._game_session.has_login))

    async def live_status(self, channel_id: str) -> Optional[LiveStatus]:
        """Get a live status info of broadcaster.

        Parameters
        ----------
        channel_id : str
            The channel ID of broadcaster

        Returns
        -------
        Optional[LiveStatus]
            Return LiveStatus info. Sometimes the broadcaster is not broadcasting, returns None.
        """
        res = await self._api_session.live_status(channel_id=channel_id)
        return res.content

    async def live_detail(self, channel_id: str) -> Optional[LiveDetail]:
        """Get a live detail info of broadcaster.

        Parameters
        ----------
        channel_id : str
            The channel ID of broadcaster

        Returns
        -------
        Optional[LiveDetail]
            Return LiveDetail info. Sometimes the broadcaster is not broadcasting, returns None.
        """
        res = await self._api_session.live_detail(channel_id=channel_id)
        return res.content

    async def user(self) -> User:
        """Get my user info.
        This method should be used after login.

        Returns
        -------
        User
            Information for logged-in user.
        """
        res = await self._game_session.user()
        return res.content

    async def search_channel(self, keyword: str) -> list[Channel]:
        """Search the channel with keyword.

        Parameters
        ----------
        keyword : str
            A keyword to search channel

        Returns
        -------
        list[Channel]
            Returns channels with searching.
        """
        res = await self._api_session.search_channel(keyword=keyword)
        data = res.content.data
        return [x.channel for x in data]

    async def search_video(self, keyword: str) -> list[Video]:
        """Search the video with keyword.

        Parameters
        ----------
        keyword : str
            A keyword to search video

        Returns
        -------
        list[Video]
            Returns videos with searching.
        """
        res = await self._api_session.search_video(keyword=keyword)
        data = res.content.data

        # Inject Channel info
        for i, x in enumerate(data):
            data[i].video.channel = x.channel

        return [x.video for x in data]

    async def search_live(self, keyword: str) -> list[Live]:
        """Search the live with keyword.

        Parameters
        ----------
        keyword : str
            A keyword to search live

        Returns
        -------
        list[Video]
            Returns lives with searching.
        """
        res = await self._api_session.search_live(keyword=keyword)
        data = res.content.data

        # Inject Channel info
        for i, x in enumerate(data):
            data[i].live.channel = x.channel

        return [x.live for x in data]

    async def autocomplete(self, keyword: str) -> list[str]:
        """Get a auto-completed keyword.

        Parameters
        ----------
        keyword : str
            Incomplete keywords

        Returns
        -------
        list[str]
            Autocompleted keywords
        """
        res = await self._api_session.autocomplete(keyword=keyword)
        data = res.content.data
        return data

    def manage(self, channel_id: Optional[str] = None) -> ManageClient:
        """Get a client provided broadcast management functionality.

        Parameters
        ----------
        channel_id : Optional[str]
            A channel id to manage broadcasts.
            The default value is the last channel id used.
            If initally use the manage method and don't have a channel_id argument,
            it will raise a :exc:`TypeError` exception.

        Returns
        -------
        ManageClient
            Return a client provided broadcast management functionality.
        """
        if channel_id is None:
            if self._latest_manage_client_id is None:
                raise TypeError("manage() missing 1 required argument: 'channel_id'")

            channel_id = self._latest_manage_client_id

        if channel_id not in self._manage_client.keys():
            self._manage_client[channel_id] = ManageClient(channel_id, self)
        self._latest_manage_client_id = channel_id
        return self._manage_client[channel_id]
