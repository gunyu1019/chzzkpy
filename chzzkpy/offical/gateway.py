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
import base64
import functools
import time
import json
import socketio
import six

from typing import Optional, Literal, TYPE_CHECKING
from urllib.parse import parse_qs
from yarl import URL

from .base_model import ChzzkModel
from .enums import EnginePacketType, SocketPacketType, get_enum

if TYPE_CHECKING:
    from .state import ConnectionState

binary_types = (bytes, bytearray)


class SessionKey(ChzzkModel):
    url: str


class OpenPacketInfo(ChzzkModel):
    sid: str
    upgrades: list[str]
    ping_interval: int
    ping_timeout: int


class EnginePacket:
    """Engine.IO packet."""
    def __init__(self, packet_type=EnginePacketType.NOOP, data=None):
        self.packet_type = packet_type
        self.data = data
        self.encode_cache = None
        
        if isinstance(data, str):
            self.binary = False
        elif isinstance(data, binary_types):
            self.binary = True
        else:
            self.binary = False
        
        if self.binary and self.packet_type != EnginePacketType.MESSAGE:
            raise ValueError('Binary packets can only be of type MESSAGE')
    
    def encode(self, b64=False):
        if self.encode_cache:
            return self.encode_cache
        if self.binary:
            if b64:
                encoded_packet = f'b{base64.b64encode(self.data).decode('utf-8')}'
            else:
                encoded_packet = self.data
        else:
            encoded_packet = str(self.packet_type.value)
            if isinstance(self.data, str):
                encoded_packet += self.data
            elif isinstance(self.data, dict) or isinstance(self.data, list):
                encoded_packet += json.dumps(self.data, separators=(',', ':'))
            elif self.data is not None:
                encoded_packet += str(self.data)
        self.encode_cache = encoded_packet
        return encoded_packet
    
    @classmethod
    def decode(cls, encoded_packet):
        """Decode a transmitted package."""
        binary = isinstance(encoded_packet, binary_types)
        if not binary and len(encoded_packet) == 0:
            raise ValueError('Invalid empty packet received')
        
        if not binary and encoded_packet[0] == 'b':
            binary = True
            packet_type = EnginePacketType.MESSAGE
            data = base64.b64decode(encoded_packet[1:])
            return cls(packet_type, data)
        
        if binary and not isinstance(encoded_packet, bytes):
            encoded_packet = bytes(encoded_packet)
        
        if binary:
            packet_type = EnginePacketType.MESSAGE
            data = encoded_packet
            return cls(packet_type, data)
        
        packet_type = get_enum(EnginePacketType, int(encoded_packet[0]))
        try:
            data = json.loads(encoded_packet[1:])
            if isinstance(data, int):
                raise ValueError
        except ValueError:
            data = encoded_packet[1:]
        return cls(packet_type, data)


class Payload:
    max_decode_packets = 16

    def __init__(self, packets=None):
        self.packets: list[EnginePacket] = packets or []

    def encode(self, jsonp_index=None):
        encoded_payload = ''
        for pkt in self.packets:
            if encoded_payload:
                encoded_payload += '\x1e'
            encoded_payload += pkt.encode(b64=True)
        if jsonp_index is not None:
            encoded_payload = f"___eio[{jsonp_index}]({encoded_payload.replace('"', '\\"')});"
        return encoded_payload

    @classmethod
    def decode(cls, encoded_payload):
        if len(encoded_payload) == 0:
            return

        # JSONP POST payload starts with 'd='
        if encoded_payload.startswith('d='):
            encoded_payload = parse_qs(encoded_payload)['d'][0]

        encoded_packets = encoded_payload.split('\x1e')

        if len(encoded_packets) > cls.max_decode_packets:
            raise ValueError('Too many packets in payload')
        
        return cls(packets=[
            EnginePacket(encoded_packet=encoded_packet)
            for encoded_packet in encoded_packets
        ])


class SocketPacket(object):
    """Socket.IO packet."""
    def __init__(self, packet_type=SocketPacketType.EVENT, data=None, namespace=None, id=None, binary=None):
        self.packet_type = packet_type
        self.data = data
        self.namespace = namespace
        self.id = id
        if binary or (binary is None and self._data_is_binary(self.data)):
            if self.packet_type == SocketPacketType.EVENT:
                self.packet_type = SocketPacketType.BINARY_EVENT
            elif self.packet_type == SocketPacketType.ACK:
                self.packet_type = SocketPacketType.BINARY_ACK
            else:
                raise ValueError('Packet does not support binary payload.')
        self.attachment_count = 0
        self.attachments = []

    def encode(self):
        """Encode the packet for transmission.

        If the packet contains binary elements, this function returns a list
        of packets where the first is the original packet with placeholders for
        the binary components and the remaining ones the binary attachments.
        """
        encoded_packet = six.text_type(self.packet_type)
        if self.packet_type == SocketPacketType.BINARY_EVENT or self.packet_type == SocketPacketType.BINARY_ACK:
            data, attachments = self._deconstruct_binary(self.data)
            encoded_packet += six.text_type(len(attachments)) + '-'
        else:
            data = self.data
            attachments = None
        needs_comma = False
        if self.namespace is not None and self.namespace != '/':
            encoded_packet += self.namespace
            needs_comma = True
        if self.id is not None:
            if needs_comma:
                encoded_packet += ','
                needs_comma = False
            encoded_packet += six.text_type(self.id)
        if data is not None:
            if needs_comma:
                encoded_packet += ','
            encoded_packet += json.dumps(data, separators=(',', ':'))
        if attachments is not None:
            encoded_packet = [encoded_packet] + attachments
        return encoded_packet

    def decode(self, encoded_packet):
        """Decode a transmitted package.

        The return value indicates how many binary attachment packets are
        necessary to fully decode the packet.
        """
        ep = encoded_packet
        try:
            self.packet_type = int(ep[0:1])
        except TypeError:
            self.packet_type = ep
            ep = ''
        self.namespace = None
        self.data = None
        ep = ep[1:]
        dash = ep.find('-')
        attachment_count = 0
        if dash > 0 and ep[0:dash].isdigit():
            attachment_count = int(ep[0:dash])
            ep = ep[dash + 1:]
        if ep and ep[0:1] == '/':
            sep = ep.find(',')
            if sep == -1:
                self.namespace = ep
                ep = ''
            else:
                self.namespace = ep[0:sep]
                ep = ep[sep + 1:]
            q = self.namespace.find('?')
            if q != -1:
                self.namespace = self.namespace[0:q]
        if ep and ep[0].isdigit():
            self.id = 0
            while ep and ep[0].isdigit():
                self.id = self.id * 10 + int(ep[0])
                ep = ep[1:]
        if ep:
            self.data = json.loads(ep)
        return attachment_count

    def add_attachment(self, attachment):
        if self.attachment_count <= len(self.attachments):
            raise ValueError('Unexpected binary attachment')
        self.attachments.append(attachment)
        if self.attachment_count == len(self.attachments):
            self.reconstruct_binary(self.attachments)
            return True
        return False

    def reconstruct_binary(self, attachments):
        """Reconstruct a decoded packet using the given list of binary
        attachments.
        """
        self.data = self._reconstruct_binary_internal(self.data,
                                                      self.attachments)

    def _reconstruct_binary_internal(self, data, attachments):
        if isinstance(data, list):
            return [self._reconstruct_binary_internal(item, attachments)
                    for item in data]
        elif isinstance(data, dict):
            if data.get('_placeholder') and 'num' in data:
                return attachments[data['num']]
            else:
                return {key: self._reconstruct_binary_internal(value,
                                                               attachments)
                        for key, value in six.iteritems(data)}
        else:
            return data

    def _deconstruct_binary(self, data):
        """Extract binary components in the packet."""
        attachments = []
        data = self._deconstruct_binary_internal(data, attachments)
        return data, attachments

    def _deconstruct_binary_internal(self, data, attachments):
        if isinstance(data, six.binary_type):
            attachments.append(data)
            return {'_placeholder': True, 'num': len(attachments) - 1}
        elif isinstance(data, list):
            return [self._deconstruct_binary_internal(item, attachments)
                    for item in data]
        elif isinstance(data, dict):
            return {key: self._deconstruct_binary_internal(value, attachments)
                    for key, value in six.iteritems(data)}
        else:
            return data

    def _data_is_binary(self, data):
        """Check if the data contains binary components."""
        if isinstance(data, six.binary_type):
            return True
        elif isinstance(data, list):
            return functools.reduce(
                lambda a, b: a or b, [self._data_is_binary(item)
                                      for item in data], False)
        elif isinstance(data, dict):
            return functools.reduce(
                lambda a, b: a or b, [self._data_is_binary(item)
                                      for item in six.itervalues(data)],
                False)
        else:
            return False


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