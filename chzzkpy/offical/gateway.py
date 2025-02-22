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

import aiohttp
import base64
import time
import socketio
import inspect

from pydantic import Field
from typing import Optional, Literal
from urllib.parse import parse_qs
from yarl import URL

from .base_model import ChzzkModel
from .enums import PackageType

binary_types = (bytes, bytearray)


class SessionKey(ChzzkModel):
    url: str


class Packet:
    """Engine.IO packet."""
    def __init__(self, packet_type=PackageType.NOOP, data=None, encoded_packet=None):
        self.packet_type = packet_type
        self.data = data
        self.encode_cache = None
        if isinstance(data, str):
            self.binary = False
        elif isinstance(data, binary_types):
            self.binary = True
        else:
            self.binary = False
        if self.binary and self.packet_type != PackageType.MESSAGE:
            raise ValueError('Binary packets can only be of type MESSAGE')
        if encoded_packet is not None:
            self.decode(encoded_packet)

    def encode(self, b64=False):
        if self.encode_cache:
            return self.encode_cache
        if self.binary:
            if b64:
                encoded_packet = f'b{base64.b64encode(self.data).decode(
                    'utf-8')}'
            else:
                encoded_packet = self.data
        else:
            encoded_packet = str(self.packet_type)
            if isinstance(self.data, str):
                encoded_packet += self.data
            elif isinstance(self.data, dict) or isinstance(self.data, list):
                encoded_packet += self.json.dumps(self.data,
                                                  separators=(',', ':'))
            elif self.data is not None:
                encoded_packet += str(self.data)
        self.encode_cache = encoded_packet
        return encoded_packet

    def decode(self, encoded_packet):
        """Decode a transmitted package."""
        self.binary = isinstance(encoded_packet, binary_types)
        if not self.binary and len(encoded_packet) == 0:
            raise ValueError('Invalid empty packet received')
        b64 = not self.binary and encoded_packet[0] == 'b'
        if b64:
            self.binary = True
            self.packet_type = PackageType.MESSAGE
            self.data = base64.b64decode(encoded_packet[1:])
        else:
            if self.binary and not isinstance(encoded_packet, bytes):
                encoded_packet = bytes(encoded_packet)
            if self.binary:
                self.packet_type = PackageType.MESSAGE
                self.data = encoded_packet
            else:
                self.packet_type = int(encoded_packet[0])
                try:
                    self.data = self.json.loads(encoded_packet[1:])
                    if isinstance(self.data, int):
                        raise ValueError
                except ValueError:
                    self.data = encoded_packet[1:]


class Payload:
    max_decode_packets = 16

    def __init__(self, packets=None, encoded_payload=None):
        self.packets = packets or []
        if encoded_payload is not None:
            self.decode(encoded_payload)

    def encode(self, jsonp_index=None):
        encoded_payload = ''
        for pkt in self.packets:
            if encoded_payload:
                encoded_payload += '\x1e'
            encoded_payload += pkt.encode(b64=True)
        if jsonp_index is not None:
            encoded_payload = f"___eio[{jsonp_index}]({encoded_payload.replace('"', '\\"')});"
        return encoded_payload

    def decode(self, encoded_payload):
        self.packets = []

        if len(encoded_payload) == 0:
            return

        # JSONP POST payload starts with 'd='
        if encoded_payload.startswith('d='):
            encoded_payload = parse_qs(
                encoded_payload)['d'][0]

        encoded_packets = encoded_payload.split('\x1e')
        if len(encoded_packets) > self.max_decode_packets:
            raise ValueError('Too many packets in payload')
        self.packets = [Packet(encoded_packet=encoded_packet)
                        for encoded_packet in encoded_packets]


class ChzzkGateway:
    def __init__(self, base_url, session, session_id, transport):
        self.current_transport: Literal['polling', 'websocket'] = transport
        self.base_url: URL = base_url
        self.session_id = session_id

        self.session: aiohttp.ClientSession = session
        self.webscoket: Optional[aiohttp.ClientWebSocketResponse] = None
        self.state: Literal['connected', 'disconnected'] = "connected"

    @staticmethod
    def _get_engineio_url(url: str | URL, transport: Literal['polling', 'websocket'], ssl: bool = True) -> URL:
        new_url = url
        if not isinstance(url, URL):
            new_url = URL(url)

        if transport == "polling":
            new_url = new_url.with_scheme("https" if ssl else "http")
        else:
            new_url = new_url.with_scheme("wss" if ssl else "ws")
        
        return new_url

    @staticmethod
    def _get_timestamp_url(url: URL) -> URL:
        query = url.query
        if "t" in query.keys():
            return url
    
        query["t"] = str(time.time())
        return url.with_query(query=query)

    @classmethod
    async def connect(cls, url: str | URL):
        return
    
    @classmethod
    async def _connect_polling(cls, url: str | URL, session: aiohttp.ClientSession):
        base_url = cls._get_engineio_url(url=url, transport="polling")
        base_url = cls._get_timestamp_url(url)
        connection_response = await session.request("GET", base_url)

        if connection_response.status < 200 or connection_response.status >= 300:
            # Connection Failed
            return
        
        raw_payload = (await connection_response.read()).decode('utf-8')
        payload = Payload(encoded_payload=raw_payload)

        open_packet = payload.packets[0]
        session_id = open_packet.data['sid']
        upgrades = open_packet.data['upgrades']
        ping_interval = int(open_packet.data['pingInterval']) / 1000.0
        ping_timeout = int(open_packet.data['pingTimeout']) / 1000.0
        current_transport = 'polling'
        
        query = base_url.query
        query["sid"] = session_id
        base_url = base_url.with_query(query)

        for packet in payload.packets[1:]:
            # receive_packet
            pass

        if "websocket" in upgrades:
            await cls._connect_websocket(url)
        return
    
    @classmethod
    async def _connect_websocket(cls, url: str | URL, session: aiohttp.ClientSession):
        base_url = cls.get_engineio_url(url=url, transport="websocket")
        base_url = cls._get_timestamp_url(url)

        # extra_options = {'timeout': request_timeout}
        socket = await session.ws_connect(base_url)
        return
