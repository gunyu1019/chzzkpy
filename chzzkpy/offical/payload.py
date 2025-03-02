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

import functools

from urllib.parse import parse_qs
from .packet import Packet


class Payload:
    max_decode_packets = 16

    def __init__(self, packets=None):
        self.packets: list[Packet] = packets or []

    def encode(self, jsonp_index=None):
        encoded_payload = b""
        for packet in self.packets:
            encoded_packet = packet.encode()
            content_length = len(encoded_packet)
            encoded_content_length = b""
            while content_length > 0:
                encoded_content_length = (
                    content_length % 10
                ).to_bytes() + encoded_content_length
                content_length //= 10

            encoded_payload += (
                b"\x00"  # Binrary Key
                + encoded_content_length
                + b"\xff"
                + encoded_packet.encode()
            )
        if jsonp_index is not None:
            encoded_payload = (
                b"___eio["
                + jsonp_index.encode()
                + b"]("
                + encoded_payload.replace(b'"', b'\\"')
                + b");"
            )
        return encoded_payload

    @classmethod
    def decode(cls, encoded_payload: bytes):
        if len(encoded_payload) == 0:
            return

        # JSONP POST payload starts with 'd='
        if encoded_payload.startswith(b"d="):
            encoded_payload = parse_qs(encoded_payload)[b"d"][0]

        is_binrary = encoded_payload.find(b"\xff") > -1
        packets = []
        index = 0

        if not is_binrary:
            encoded_payload = encoded_payload.decode("utf-8")
            while index < len(encoded_payload):
                content_length, content = encoded_payload[index:].split(":", maxsplit=1)
                packets.append(Packet.decode(content[: int(content_length)]))
                index += int(content_length)
        else:
            while index < len(encoded_payload):
                is_binrary = int(encoded_payload[index])
                index += 1

                raw_content_length, content = encoded_payload[index:].split(
                    b"\xff", maxsplit=1
                )

                index += len(raw_content_length) + 1
                content_length = functools.reduce(
                    lambda d, s: d * 10 + s, raw_content_length
                )

                # Binrary is not supported. (TODO)
                if not is_binrary:
                    content = content[: int(content_length)].decode("utf-8")
                    packets.append(Packet.decode(content))
                index += int(content_length)
        return cls(packets=packets)
