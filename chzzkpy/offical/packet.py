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

import json

from typing import Any, Optional
from urllib.parse import parse_qs

from .enums import EnginePacketType, SocketPacketType, get_enum


class Packet:
    """ Implement integrated packet(socket.io + engine.io)
    Consider the environment, the attachments does not implement.
    """
    def __init__(
            self, 
            engine_packet_type: Optional[EnginePacketType] = None, 
            socket_packet_type: Optional[SocketPacketType] = None,
            data: Optional[Any] = None,
            *,
            packet_id: Optional[int] = None,
            namespace: Optional[str] = None,
    ):
        self.engine_packet_type = engine_packet_type or EnginePacketType.NOOP
        self.socket_packet_type = socket_packet_type

        self.id = packet_id
        self.data = data
        self.namespace = namespace

    @classmethod
    def _decode_socket(cls, engine_packet_type, payload, json_serialize = None):
        packet_type = get_enum(SocketPacketType, int(payload[0:1]))
        data = payload[1:]

        # Empty Data
        if len(data) == 0:
            return cls(engine_packet_type, packet_type)
        
        # Decode Attachment (Binaray)
        attachment_separator = data.find('-')
        if attachment_separator > 0 and data[0:attachment_separator]:
            # Unused attachment feature in chzzk Session API.
            # attachment_count = data[0:attachment_separator]
            data = data[attachment_separator + 1:]
        
        # Decode Namespace
        namespace = None
        if len(data) > 0 and data.startswith("/"):
            namespace_separtor = data.find(',')
            if namespace_separtor == -1:
                namespace = data
                data = str()
            else:
                namespace = data[0:namespace_separtor]
                data = data[namespace_separtor + 1:]

            query = namespace.find("?")
            if query >= 0:
                namespace = namespace[0:query]

        # Decode Packet ID
        packet_id = None
        if len(data) > 0 and data[0].isdigit():
            packet_id = data[0]
            while len(data) > 0 and data[0].isdigit():
                packet_id *= 10
                packet_id += int(data[0])
                data = data[1:]

        if len(data) > 0:
            data = json_serialize(data)
        return cls(engine_packet_type, packet_type, data, packet_id=packet_id, namespace=namespace)

    @classmethod
    def decode(cls, payload, json_serialize = None):
        json_serialize = json_serialize or json.loads
        packet_type = get_enum(EnginePacketType, int(payload[0]))
        
        if packet_type == EnginePacketType.MESSAGE:
            return cls._decode_socket(packet_type, payload[1:])
        
        try:
            data = json_serialize(payload[1:])
            if isinstance(data, int):
                raise ValueError
        except ValueError:
            data = payload[1:]
        return cls(packet_type, None, data)
    
    @property
    def is_socket_packet(self) -> bool:
        return self.socket_packet_type is not None
    
    def encode(self, json_serialize = None) -> str:
        json_serialize = json_serialize or json.dumps
        encoded_packet = str(self.engine_packet_type.value)
        if self.is_socket_packet:
            encoded_packet += str(self.socket_packet_type)
            encoded_data = []

            data = (
                json_serialize(self.data, separators=(",", ":"))
                if self.data is not None else
                None
            )

            if self.namespace is not None:
                encoded_data.append(self.namespace)
            
            if self.id is not None:
                encoded_data.append(
                    str(self.id) +
                    data if data is not None else ""
                )
            elif data is not None:
                encoded_data.append(data)
            
            encoded_packet += ",".join(encoded_data)
            return encoded_packet
        if isinstance(self.data, str):
            encoded_packet += self.data
        elif isinstance(self.data, dict) or isinstance(self.data, list):
            encoded_packet += json_serialize(self.data, separators=(',', ':'))
        elif self.data is not None:
            encoded_packet += str(self.data) 
        return encoded_packet


class Payload:
    max_decode_packets = 16

    def __init__(self, packets=None):
        self.packets: list[Packet] = packets or []

    def encode(self, jsonp_index=None):
        encoded_payload = '\x1e'.join([pkt.encode(b64=True) for pkt in self.packets])
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
            Packet.decode(encoded_packet)
            for encoded_packet in encoded_packets
        ])
