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

import aiohttp
import time

from typing import Optional, Literal, TYPE_CHECKING
from yarl import URL

from .base_model import ChzzkModel
from .enums import EnginePacketType, SocketPacketType

if TYPE_CHECKING:
    from .state import ConnectionState


class SessionKey(ChzzkModel):
    url: str


class OpenPacketInfo(ChzzkModel):
    sid: str
    upgrades: list[str]
    ping_interval: int
    ping_timeout: int


class ChzzkGateway:
    def __init__(
            self, 
            base_url: URL, 
            session: aiohttp.ClientSession, 
            state: ConnectionState,
            current_transport: Literal['polling', 'websocket'],
            open_packet_info: OpenPacketInfo,
            session_id: Optional[str] = None
    ):
        self.current_transport = current_transport
        self.upgrades = open_packet_info.upgrades
        self.ping_interval = open_packet_info.ping_interval / 1000.0
        self.ping_timeout = open_packet_info.ping_timeout / 1000.0

        self.base_url = base_url
        self.session_id = session_id or open_packet_info.sid

        self.session: aiohttp.ClientSession = session
        self.state: ConnectionState = state
        self.websocket: Optional[aiohttp.ClientWebSocketResponse] = None

        self.is_connected = True

    @staticmethod
    def _get_engineio_url(
        url: str | URL, 
        engine_path: str, 
        transport: Literal['polling', 'websocket'], 
        ssl: bool = True
    ) -> URL:
        new_url = url
        if not isinstance(url, URL):
            new_url = URL(url)

        if transport == "polling":
            new_url = new_url.with_scheme("https" if ssl else "http")
        else:
            new_url = new_url.with_scheme("wss" if ssl else "ws")

        new_url = new_url.with_path(engine_path)

        query = new_url.query.copy()
        query.update({

        })
        new_url = new_url.with_query()
        return new_url

    @staticmethod
    def _get_timestamp_url(url: URL) -> URL:
        query = url.query.copy()
        if "t" in query.keys():
            return url
    
        query["t"] = str(time.time())
        return url.with_query(query=query)

    @classmethod
    async def connect(
        cls, 
        url: str | URL, 
        state: ConnectionState, 
        session: aiohttp.ClientSession
    ):
        engine_path = "socket.io"
        return await cls._connect_polling(url, engine_path, state, session)
    
    @classmethod
    async def _connect_polling(
        cls,
        url: str | URL, 
        engine_path: str,
        state: ConnectionState,
        session: aiohttp.ClientSession
    ):
        base_url = cls._get_engineio_url(url=url, engine_path=engine_path, transport="polling")
        base_url = cls._get_timestamp_url(url)
        connection_response = await session.request("GET", base_url)

        if connection_response.status < 200 or connection_response.status >= 300:
            # Connection Failed
            return
        
        raw_payload = (await connection_response.read()).decode('utf-8')
        payload = Payload.decode(raw_payload)

        raw_open_packet = payload.packets[0]
        open_packet = OpenPacketInfo.model_validate(raw_open_packet.data)

        for packet in payload.packets[1:]:
            # receive_packet
            pass

        if "websocket" in open_packet.upgrades:
            return await cls._connect_websocket(
                url=url,
                engine_path=engine_path,
                state=state,
                session=session,
                open_packet=open_packet
            )
        
        query = base_url.query.copy()
        query["sid"] = open_packet.sid
        base_url = base_url.with_query(query)

        return cls(
            base_url = base_url,
            session = session,
            state=state,
            current_transport = "polling",
            open_packet_info=open_packet,
            session_id = open_packet.sid,
        )
    
    @classmethod
    async def _connect_websocket(
        cls, 
        url: str | URL, 
        engine_path: str,
        state: ConnectionState,
        session: aiohttp.ClientSession,
        open_packet: Optional[OpenPacketInfo] = None  # For update
    ):
        base_url = cls._get_engineio_url(url=url, engine_path=engine_path, transport="websocket")
        base_url = cls._get_timestamp_url(url)

        if open_packet is not None:
            query = base_url.query.copy()
            query["sid"] = open_packet.sid
            base_url = base_url.with_query(query)
            upgrade = True
        else:
            upgrade = False

        try:
            websocket = await session.ws_connect(base_url)
        except (aiohttp.client_exceptions.WSServerHandshakeError,
                aiohttp.client_exceptions.ServerConnectionError,
                aiohttp.client_exceptions.ClientConnectionError):
            "Connection Error"
            return
        
        if upgrade:
            ping_packet = EnginePacket(EnginePacketType.PING, data='probe')

            await websocket.send_str(ping_packet.encode())
            raw_pong_packet = (await websocket.receive()).data
            pong_packet = EnginePacket.decode(raw_pong_packet)

            if pong_packet.packet_type != EnginePacketType.PONG or pong_packet.data != 'probe':
                raise ConnectionError("WebSocket upgrade failed: no PONG packet")
            
            upgrade_packet = EnginePacket(EnginePacketType.UPGRADE)
            await websocket.send_str(upgrade_packet.encode())
        else:
            raw_open_packet = (await websocket.receive()).data
            raw_open_packet = EnginePacket.decode(raw_open_packet)
            open_packet = OpenPacketInfo.model_validate(raw_open_packet)
        
            query = base_url.query.copy()
            query["sid"] = open_packet.sid
            base_url = base_url.with_query(query)
            
        session_id = open_packet.sid

        new_cls = cls(
            base_url=base_url,
            session=session,
            state=state,
            current_transport = "websocket",
            open_packet_info=open_packet,
            session_id = session_id,
        )
        new_cls.websocket = websocket
        return new_cls

    async def _read_polling(self):
        while self.is_connected:
            base_url = self._get_timestamp_url(self.base_url)
            response = await self.session.request("GET", base_url, timeout=max(self.ping_interval, self.ping_timeout) + 5)
        
            raw_payload = (await response.read()).decode('utf-8')
            payload = Payload.decode(raw_payload)

    async def _read_websocket(self):
        while self.is_connected:
            raw_payload = await self.websocket.receive(timeout=self.ping_interval + self.ping_timeout)
            payload = Payload.decode(raw_payload)

    async def _write(self):
        pass