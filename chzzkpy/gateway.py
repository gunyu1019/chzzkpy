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
import aiohttp
import logging
import time

from typing import Literal, TYPE_CHECKING
from yarl import URL

from .base_model import ChzzkModel
from .enums import EnginePacketType, SocketPacketType
from .error import HTTPException, ChatConnectFailed, ReceiveErrorPacket
from .packet import Packet
from .payload import Payload

if TYPE_CHECKING:
    from typing import Any, Callable, Optional
    from .state import ConnectionState

_log = logging.getLogger(__name__)


class OpenPacketInfo(ChzzkModel):
    sid: str
    upgrades: list[str]
    ping_interval: int
    ping_timeout: int


class ChzzkGateway:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        base_url: URL,
        session: aiohttp.ClientSession,
        current_transport: Literal["polling", "websocket"],
        open_packet_info: OpenPacketInfo,
        session_id: Optional[str] = None,
        event_hook=None,
    ):
        self.current_transport = current_transport
        self.upgrades = open_packet_info.upgrades
        self.ping_interval = open_packet_info.ping_interval / 1000.0
        self.ping_timeout = open_packet_info.ping_timeout / 1000.0

        self.base_url = base_url
        self.session_id = session_id or open_packet_info.sid

        self.loop = loop
        self.session: aiohttp.ClientSession = session
        self.websocket: Optional[aiohttp.ClientWebSocketResponse] = None

        self.is_connected = True

        self._heartbeat_receive_event = asyncio.Event()
        self._heartbeat_receive_event.clear()

        if self.current_transport == "websocket":
            self._write = self._write_websocket
            self._read_loop = self._read_websocket
        else:
            self._write = self._write_polling
            self._read_loop = self._read_polling

        self._read_background_loop: Optional[asyncio.Task] = None

        _log.debug(f"Success connected to {self.base_url.host} with socket.io gateway")

        self._event_hook: dict[
            SocketPacketType | EnginePacketType, Optional[Callable[..., Any]]
        ] = event_hook or {
            key: None for key in list(SocketPacketType) + list(EnginePacketType)
        }

        _log.debug("Start handshake task")
        self._ping_loop_task = loop.create_task(self._ping_loop())

    def set_hook(
        self, event: SocketPacketType | EnginePacketType, coro_func: Callable[..., Any]
    ):
        self._event_hook[event] = coro_func

    def remove_hook(self, event: SocketPacketType | EnginePacketType):
        self._event_hook[event] = None

    @staticmethod
    def _get_engineio_url(
        url: str | URL,
        engine_path: str,
        transport: Literal["polling", "websocket"],
        ssl: bool = True,
    ) -> URL:
        new_url = url
        if not isinstance(url, URL):
            new_url = URL(url)

        query = new_url.query.copy()

        if transport == "polling":
            new_url = new_url.with_scheme("https" if ssl else "http")
        else:
            new_url = new_url.with_scheme("wss" if ssl else "ws")

        new_url = new_url.with_path(f"{engine_path}/")

        query.extend(**{"EIO": "3", "transport": transport})
        new_url = new_url.with_query(query)
        return new_url

    @staticmethod
    def _get_timestamp_url(url: URL) -> URL:
        query = url.query.copy()
        if "t" in query.keys():
            return url

        query["t"] = str(time.time())
        return url.with_query(query)

    @classmethod
    async def connect(
        cls,
        url: str | URL,
        state: ConnectionState,
        loop: asyncio.AbstractEventLoop,
        session: aiohttp.ClientSession,
        engine_path: Optional[str] = None,
    ):
        engine_path = engine_path or "socket.io"
        gateway = await cls._connect_polling(url, engine_path, loop, session)

        for event, parsing_func in state.gateway_parsers.items():
            if parsing_func is None:
                continue
            gateway.set_hook(event, parsing_func)

        return gateway

    @classmethod
    async def _connect_polling(
        cls,
        url: str | URL,
        engine_path: str,
        loop: asyncio.AbstractEventLoop,
        session: aiohttp.ClientSession,
        event_hook: Optional[
            dict[EnginePacketType | SocketPacketType, Callable[..., Any]]
        ] = None,
    ):
        base_url = cls._get_engineio_url(
            url=url, engine_path=engine_path, transport="polling"
        )
        base_url = cls._get_timestamp_url(base_url)
        connection_response = await session.request("GET", base_url)

        if connection_response.status < 200 or connection_response.status >= 300:
            raise ChatConnectFailed.polling_connect_failed(connection_response.status)

        raw_payload = await connection_response.read()
        payload = Payload.decode(raw_payload)

        raw_open_packet = payload.packets[0]
        open_packet = OpenPacketInfo.model_validate(raw_open_packet.data)

        if "websocket" in open_packet.upgrades:
            try:
                new_cls = await cls._connect_websocket(
                    url=url,
                    engine_path=engine_path,
                    loop=loop,
                    session=session,
                    open_packet=open_packet,
                    event_hook=event_hook,
                )
            except (
                aiohttp.client_exceptions.WSServerHandshakeError,
                aiohttp.client_exceptions.ServerConnectionError,
                aiohttp.client_exceptions.ClientConnectionError,
                ChatConnectFailed,
            ):
                _log.info(
                    "Failed upgrade to websocket transport: use polling transport."
                )
                pass
            else:
                for packet in payload.packets[1:]:
                    new_cls.received_message(packet)
                return new_cls

        query = base_url.query.copy()
        query["sid"] = open_packet.sid
        base_url = base_url.with_query(query)

        new_cls = cls(
            loop=loop,
            base_url=base_url,
            session=session,
            current_transport="polling",
            open_packet_info=open_packet,
            session_id=open_packet.sid,
            event_hook=event_hook,
        )
        for packet in payload.packets:
            new_cls.received_message(packet)
        return new_cls

    @classmethod
    async def _connect_websocket(
        cls,
        url: str | URL,
        engine_path: str,
        loop: asyncio.AbstractEventLoop,
        session: aiohttp.ClientSession,
        open_packet: Optional[OpenPacketInfo] = None,  # For update,
        event_hook: Optional[
            dict[EnginePacketType | SocketPacketType, Callable[..., Any]]
        ] = None,
    ):
        base_url = cls._get_engineio_url(
            url=url, engine_path=engine_path, transport="websocket"
        )
        base_url = cls._get_timestamp_url(base_url)

        if open_packet is not None:
            query = base_url.query.copy()
            query["sid"] = open_packet.sid
            base_url = base_url.with_query(query)
            upgrade = True
        else:
            upgrade = False

        websocket = await session.ws_connect(base_url)

        if upgrade:
            ping_packet = Packet(EnginePacketType.PING, data="probe")

            await websocket.send_str(ping_packet.encode())
            raw_pong_packet = (await websocket.receive()).data
            pong_packet = Packet.decode(raw_pong_packet)

            if (
                pong_packet.engine_packet_type != EnginePacketType.PONG
                or pong_packet.data != "probe"
            ):
                raise ChatConnectFailed.websocket_upgrade_failed()

            upgrade_packet = Packet(EnginePacketType.UPGRADE)
            await websocket.send_str(upgrade_packet.encode())
        else:
            raw_open_packet = (await websocket.receive()).data
            raw_open_packet = Packet.decode(raw_open_packet)
            open_packet = OpenPacketInfo.model_validate(raw_open_packet.data)

            query = base_url.query.copy()
            query["sid"] = open_packet.sid
            base_url = base_url.with_query(query)

        session_id = open_packet.sid

        new_cls = cls(
            loop=loop,
            base_url=base_url,
            session=session,
            current_transport="websocket",
            open_packet_info=open_packet,
            session_id=session_id,
            event_hook=event_hook,
        )
        await new_cls.received_message(
            Packet(
                engine_packet_type=EnginePacketType.OPEN, data=open_packet.model_dump()
            )
        )
        new_cls.websocket = websocket
        return new_cls

    async def _read_polling(self):
        base_url = self._get_timestamp_url(self.base_url)
        response = await self.session.request(
            "GET", base_url, timeout=max(self.ping_interval, self.ping_timeout) + 5
        )

        if response.status >= 300 and response.status < 200:
            raise ReceiveErrorPacket(self.current_transport, self.status)

        raw_payload = await response.read()
        payload = Payload.decode(raw_payload)

        for packet in payload.packets:
            await self.received_message(packet)

    async def _read_websocket(self):
        message = await self.websocket.receive(
            timeout=self.ping_interval + self.ping_timeout
        )
        if message.type is aiohttp.WSMsgType.TEXT:
            data = message.data
            packet = Packet.decode(data)
            await self.received_message(packet)
        elif message.type == aiohttp.WSMsgType.ERROR:
            raise ReceiveErrorPacket(self.current_transport, self.data)

    async def _write_polling(self, data: Packet):
        write_response = await self.session.request(
            "POST", self.base_url, data=data.encode()
        )
        if write_response.status < 200 and write_response.status >= 300:
            raise HTTPException(write_response.status)
        return

    async def _write_websocket(self, data: Packet):
        await self.websocket.send_bytes(data.encode())
        return

    async def _ping_loop(self):
        while self.is_connected:
            _log.debug("Send Ping packet to server for heartbeat")
            await self.send_ping()
            try:
                await asyncio.wait_for(
                    self._heartbeat_receive_event.wait(), timeout=self.ping_timeout
                )
            except (asyncio.Timeout, asyncio.CancelledError):
                raise ConnectionError("PONG response has not been received.")
            _log.debug("Received Pong packet from server.")
            await asyncio.sleep(self.ping_interval)

    async def read(self):
        while self.is_connected:
            await self._read_loop()

    def read_in_background(self) -> asyncio.Task:
        task = self.loop.create_task(self.read())
        self._read_background_loop = task
        return task

    async def received_message(self, data: Packet):
        _log.debug(
            f"Received Packet (Engine Packet Type: {data.engine_packet_type}, "
            f"Socket Packet Type: {data.socket_packet_type}, Data: {data.data})"
        )
        if data.is_socket_packet:
            if (
                data.socket_packet_type == SocketPacketType.EVENT
                and data.id is not None
            ):
                await self.send_ack(data.id)

            func = self._event_hook.get(data.socket_packet_type)
            if func is not None:
                await func(data.data)
            return

        if data.engine_packet_type == EnginePacketType.PONG:
            self._heartbeat_receive_event.set()
        elif data.engine_packet_type == EnginePacketType.CLOSE:
            _log.warning("Received close packet, close connection.")
            await self.disconnect()

        func = self._event_hook.get(data.engine_packet_type)
        if func is not None:
            await func(data.data)
        return

    async def send(self, packet: Payload | Packet):
        if isinstance(packet, Packet):
            packet = Payload(packets=[packet])
        await self._write(packet)

    async def disconnect(self):
        if not self.is_connected:
            return

        self._ping_loop_task.cancel()
        await self.send_disconnet()
        self.is_connected = False

        if (
            self._read_background_loop is not None
            and not self._read_background_loop.cancelled()
        ):
            self._read_background_loop.cancel()
        await self.websocket.close()

    async def send_ping(self, message: Optional[str] = None):
        await self.send(Packet(EnginePacketType.PING, data=message))

    async def send_disconnet(self):
        await self.send(Packet(EnginePacketType.MESSAGE, SocketPacketType.DISCONNECT))
        await self.send(Packet(EnginePacketType.CLOSE))

    async def send_ack(self, pakcet_id: int):
        await self.send(
            Packet(EnginePacketType.MESSAGE, SocketPacketType.ACK, packet_id=pakcet_id)
        )
