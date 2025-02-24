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

from urllib.parse import parse_qs
from .packet import Packet


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
