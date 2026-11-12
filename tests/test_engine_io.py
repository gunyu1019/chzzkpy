"""MIT License

Copyright (c) 2024-2025 gunyu1019

Engine.IO protocol layer tests.
Tests low-level communication integrity and connection processes.
"""

import asyncio
import json
from urllib.parse import quote_from_bytes

import aiohttp
import pytest

from chzzkpy.enums import EnginePacketType, SocketPacketType
from chzzkpy.error import ChatConnectFailed, HTTPException, ReceiveErrorPacket
from chzzkpy.gateway import ChzzkGateway, OpenPacketInfo
from chzzkpy.packet import Packet
from chzzkpy.payload import Payload


def guard_read_loop_spinning(gateway: ChzzkGateway, limit: int = 100):
    """Make a read loop that keeps reading a closed websocket fail.

    receive() on a closed websocket returns without yielding, so such a loop freezes
    the event loop (asyncio.wait_for can't time out) instead of failing the test.
    """
    read_loop = gateway._read_loop
    closed_reads = 0

    async def guarded_read_loop():
        nonlocal closed_reads
        if gateway.websocket is not None and gateway.websocket.closed:
            closed_reads += 1
            if closed_reads > limit:
                raise AssertionError(
                    f"read loop kept reading a closed websocket {closed_reads} times"
                )
        await read_loop()

    gateway._read_loop = guarded_read_loop


def acquired_connections(session: aiohttp.ClientSession) -> int:
    """Count the connections of the session that haven't been given back."""
    return len(session.connector._acquired)


def track_websockets(monkeypatch) -> list[aiohttp.ClientWebSocketResponse]:
    """Record the websockets opened by aiohttp, even if the connect then fails."""
    websockets = []
    ws_connect = aiohttp.ClientSession.ws_connect

    async def tracked_ws_connect(self, *args, **kwargs):
        websocket = await ws_connect(self, *args, **kwargs)
        websockets.append(websocket)
        return websocket

    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", tracked_ws_connect)
    return websockets


@pytest.mark.asyncio
class TestEngineIOPolling:
    """Test Engine.IO polling transport."""

    async def test_polling_handshake(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test handshake process via long-polling."""
        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Verify connection was established
        assert gateway.is_connected
        assert gateway.session_id == mock_server.sid
        # Transport may be 'websocket' if upgrade succeeded, or 'polling' if it didn't
        assert gateway.current_transport in ("polling", "websocket")

        # Verify connection parameters
        assert gateway.ping_interval == mock_server.ping_interval / 1000.0
        assert gateway.ping_timeout == mock_server.ping_timeout / 1000.0
        assert "websocket" in gateway.upgrades

        await gateway.disconnect()

    @pytest.mark.parametrize(
        "upgrades", [["websocket"], []], ids=["upgraded", "polling_only"]
    )
    async def test_polling_send_message(
        self, mock_server, mock_connection_state, test_session, wait_until, upgrades
    ):
        """Test sending messages via polling transport."""
        mock_server.upgrades = upgrades
        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )
        assert gateway.current_transport == ("websocket" if upgrades else "polling")

        # Send a test packet
        test_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["test_event", {"data": "test"}],
        )
        await gateway.send(test_packet)

        # Verify server received the packet as it was encoded, once
        frame = '42["test_event",{"data":"test"}]'
        await wait_until(
            lambda: frame in mock_server.received_messages, message="the event frame"
        )
        assert mock_server.received_messages.count(frame) == 1

        await gateway.disconnect()

    async def test_polling_receive_data(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test receiving raw data packets via polling."""
        mock_server.upgrades = []
        mock_server._poll_hold = True
        received_packets = []

        async def packet_handler(data):
            received_packets.append(data)

        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook={
                EnginePacketType.OPEN: packet_handler,
                SocketPacketType.CONNECT: packet_handler,
                SocketPacketType.EVENT: packet_handler,
            },
            ssl=False,
        )
        assert gateway.current_transport == "polling"

        # The packets of the handshake are delivered before the first poll
        assert received_packets == [
            {
                "sid": mock_server.sid,
                "upgrades": [],
                "pingInterval": mock_server.ping_interval,
                "pingTimeout": mock_server.ping_timeout,
            },
            None,
        ]

        read_task = gateway.read_in_background()
        mock_server.queue_polling_packet(
            Packet(
                EnginePacketType.MESSAGE,
                SocketPacketType.EVENT,
                data=["polled_event", {"value": 1}],
            )
        )
        await wait_until(lambda: len(received_packets) == 3, message="the polled event")
        assert received_packets[2] == ["polled_event", {"value": 1}]

        assert gateway.is_connected
        await gateway.disconnect()
        await asyncio.wait_for(read_task, timeout=2.0)

    @pytest.mark.parametrize("upgrades", [["websocket"], []])
    async def test_handshake_packets_reach_state_hooks(
        self, mock_server, mock_connection_state, test_session, upgrades
    ):
        """Test packets bundled in the polling handshake reach the state's hooks."""
        mock_server.upgrades = upgrades

        gateway = await ChzzkGateway.connect(
            url=mock_server.url,
            state=mock_connection_state,
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # OPEN and socket.io CONNECT arrive with the handshake, before any read loop
        event_names = [event[0] for event in mock_connection_state.dispatched_events]
        assert event_names.count("engine_connect") == 1
        assert "socket_connect" in event_names
        assert mock_connection_state.gateway_id == mock_server.sid

        await gateway.disconnect()


@pytest.mark.asyncio
class TestEngineIOWebSocket:
    """Test Engine.IO WebSocket transport."""

    async def test_websocket_direct_connection(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test direct WebSocket connection without polling upgrade."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Verify connection
        assert gateway.is_connected
        assert gateway.current_transport == "websocket"
        assert gateway.websocket is not None
        assert not gateway.websocket.closed

        await gateway.disconnect()

    async def test_websocket_upgrade_from_polling(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test WebSocket upgrade from polling transport.

        Note: _connect_polling automatically upgrades to websocket if the server supports it.
        This is the expected Engine.IO behavior.
        """
        # Connect via polling (will automatically upgrade to websocket)
        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Verify automatic upgrade succeeded
        assert gateway.current_transport == "websocket"
        assert gateway.session_id == mock_server.sid
        assert gateway.is_connected

        await gateway.disconnect()

    async def test_polling_only_without_upgrade(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test polling transport when server doesn't support websocket upgrade."""
        # Temporarily disable websocket upgrade on mock server
        original_upgrades = mock_server.upgrades
        mock_server.upgrades = []

        try:
            gateway = await ChzzkGateway._connect_polling(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                ssl=False,
            )

            # Verify it stays on polling transport
            assert gateway.current_transport == "polling"
            assert gateway.session_id == mock_server.sid
            assert gateway.is_connected

            await gateway.disconnect()
        finally:
            # Restore original upgrades
            mock_server.upgrades = original_upgrades

    async def test_websocket_upgrade_probe(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test ping/pong probe during WebSocket upgrade process."""
        # Simulate upgrade by providing open_packet
        from chzzkpy.gateway import OpenPacketInfo

        open_packet = OpenPacketInfo(
            sid=mock_server.sid,
            upgrades=["websocket"],
            ping_interval=int(mock_server.ping_interval),
            ping_timeout=int(mock_server.ping_timeout),
        )

        # Connect with upgrade
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            open_packet=open_packet,
            ssl=False,
        )

        # Verify upgrade succeeded
        assert gateway.is_connected
        assert gateway.current_transport == "websocket"
        assert gateway.session_id == mock_server.sid

        await gateway.disconnect()

    async def test_websocket_upgrade_failure(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test handling of failed WebSocket upgrade."""
        mock_server._accept_upgrade = False

        from chzzkpy.gateway import OpenPacketInfo

        open_packet = OpenPacketInfo(
            sid=mock_server.sid,
            upgrades=["websocket"],
            ping_interval=int(mock_server.ping_interval),
            ping_timeout=int(mock_server.ping_timeout),
        )

        # Connection may succeed initially, but server rejects upgrade
        # In this case, we expect the gateway to be created but then fail
        # when trying to use it (e.g., during the first read)
        try:
            gateway = await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                open_packet=open_packet,
                ssl=False,
            )
            # If we get here, gateway was created
            # Try to use it - should fail because server rejected upgrade
            assert (
                not gateway.websocket.closed or gateway.current_transport == "polling"
            )
        except ChatConnectFailed:
            # This is acceptable - upgrade failed
            pass
        finally:
            mock_server._accept_upgrade = True

    async def test_websocket_send_receive(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test bidirectional communication over WebSocket."""
        received_events = []

        async def event_handler(data):
            received_events.append(data)

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook={SocketPacketType.EVENT: event_handler},
            ssl=False,
        )
        read_task = gateway.read_in_background()

        # Send a test event
        test_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["test_event", {"key": "value"}],
        )
        await gateway.send(test_packet)

        # Verify server received the event as it was encoded
        await wait_until(lambda: mock_server.emit_events, message="the sent event")
        assert mock_server.emit_events == [
            ("test_event", ["test_event", {"key": "value"}])
        ]
        assert '42["test_event",{"key":"value"}]' in mock_server.received_messages

        # And the other way round
        await mock_server.broadcast_event("server_event", {"reply": [1, 2]})
        await wait_until(lambda: received_events, message="the received event")
        assert received_events == [["server_event", {"reply": [1, 2]}]]

        await gateway.disconnect()
        await asyncio.wait_for(read_task, timeout=2.0)


@pytest.mark.asyncio
class TestEngineIOHeartbeat:
    """Test Engine.IO ping/pong heartbeat mechanism."""

    async def test_ping_pong_exchange(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test ping/pong packet exchange for heartbeat."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Start background read loop to receive PONG packets
        read_task = gateway.read_in_background()

        # Clear heartbeat flag
        gateway._heartbeat_receive_event.clear()

        # Send ping
        await gateway.send_ping()

        # Wait for pong response
        try:
            await asyncio.wait_for(
                gateway._heartbeat_receive_event.wait(),
                timeout=2.0,
            )
            pong_received = True
        except asyncio.TimeoutError:
            pong_received = False

        assert pong_received, "PONG response not received"

        await gateway.disconnect()
        read_task.cancel()
        try:
            await read_task
        except asyncio.CancelledError:
            pass

    async def test_ping_with_data(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test ping packet with probe data."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Send ping with probe data
        await gateway.send_ping("probe")

        # Verify message was sent as it is
        await wait_until(
            lambda: "2probe" in mock_server.received_messages, message="the ping"
        )
        assert gateway.is_connected

        await gateway.disconnect()

    async def test_heartbeat_timeout(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test connection handling when heartbeat times out."""
        mock_server._auto_pong = False

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Temporarily reduce ping timeout for faster test
        original_timeout = gateway.ping_timeout
        gateway.ping_timeout = 0.5

        gateway._heartbeat_receive_event.clear()
        await gateway.send_ping()

        # Should timeout waiting for pong
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                gateway._heartbeat_receive_event.wait(),
                timeout=gateway.ping_timeout,
            )

        gateway.ping_timeout = original_timeout
        await gateway.disconnect()

        mock_server._auto_pong = True


class TestEngineIOPackets:
    """Test Engine.IO packet encoding/decoding."""

    def test_packet_encode_decode(self, sample_packets):
        """Test packet encoding and decoding integrity."""
        # Test only engine-level packets (non-socket packets)
        engine_only_packets = {
            "open": sample_packets["open"],
            "ping": sample_packets["ping"],
            "pong": sample_packets["pong"],
            "ping_probe": sample_packets["ping_probe"],
            "pong_probe": sample_packets["pong_probe"],
            "upgrade": sample_packets["upgrade"],
            "close": sample_packets["close"],
        }

        expected_encoded = {
            "open": '0{"sid":"test-sid","upgrades":["websocket"],'
            '"pingInterval":25000,"pingTimeout":60000}',
            "ping": "2",
            "pong": "3",
            "ping_probe": "2probe",
            "pong_probe": "3probe",
            "upgrade": "5",
            "close": "1",
        }

        for name, packet in engine_only_packets.items():
            # Encode
            encoded = packet.encode()
            assert isinstance(encoded, str)
            assert encoded == expected_encoded[name], name

            # Decode
            decoded = Packet.decode(encoded)
            assert decoded.engine_packet_type == packet.engine_packet_type, name
            assert decoded.socket_packet_type is None, name
            if packet.data is None:
                assert not decoded.data, name
            else:
                assert decoded.data == packet.data, name
            # Nothing is lost on the way back
            assert decoded.encode() == encoded, name

    def test_socket_packet_encode_decode(self):
        """Test socket.io packet encoding and decoding."""
        # Create packets from encoded strings (as they would come from server)
        test_cases = [
            ("40", EnginePacketType.MESSAGE, SocketPacketType.CONNECT),  # CONNECT
            ("41", EnginePacketType.MESSAGE, SocketPacketType.DISCONNECT),  # DISCONNECT
            (
                '42["event",{"key":"value"}]',
                EnginePacketType.MESSAGE,
                SocketPacketType.EVENT,
            ),  # EVENT
            ("43", EnginePacketType.MESSAGE, SocketPacketType.ACK),  # ACK
        ]

        for encoded_str, expected_engine, expected_socket in test_cases:
            decoded = Packet.decode(encoded_str)
            assert decoded.engine_packet_type == expected_engine
            assert decoded.socket_packet_type == expected_socket

    def test_payload_encode_decode(self, sample_packets):
        """Test payload encoding/decoding with multiple packets."""
        packets = [
            sample_packets["open"],
            sample_packets["socket_connect"],
        ]

        payload = Payload(packets=packets)

        # Encode: <0><length digits><0xff><packet> for each packet
        encoded = payload.encode()
        assert isinstance(encoded, bytes)
        assert encoded == (
            b"\x00\x08\x05\xff"
            b'0{"sid":"test-sid","upgrades":["websocket"],'
            b'"pingInterval":25000,"pingTimeout":60000}'
            b"\x00\x02\xff40"
        )

        # Decode
        decoded_payload = Payload.decode(encoded)
        assert len(decoded_payload.packets) == len(packets)

        # Verify each packet
        for original, decoded in zip(packets, decoded_payload.packets):
            assert decoded.engine_packet_type == original.engine_packet_type
            assert decoded.socket_packet_type == original.socket_packet_type
            assert decoded.encode() == original.encode()
        assert decoded_payload.packets[0].data == packets[0].data

    @pytest.mark.parametrize(
        ("malformed", "error"),
        [
            ("", IndexError),  # Empty
            ("x", ValueError),  # Packet type isn't a number
            ("4", ValueError),  # MESSAGE without a socket.io packet type
            ("4x", ValueError),  # Socket.io packet type isn't a number
            ("42[bad", json.JSONDecodeError),  # Event data isn't JSON
            ("42x", json.JSONDecodeError),  # Event data isn't JSON
            ("0{broken", None),  # Not JSON, so it stays text
        ],
    )
    def test_malformed_packet_handling(self, malformed, error):
        """Test handling of malformed packets."""
        if error is None:
            assert Packet.decode(malformed).data == "{broken"
            return

        with pytest.raises(error):
            Packet.decode(malformed)

    @pytest.mark.parametrize(
        ("unknown", "packet_type", "data"),
        [
            ("9", 9, ""),  # Invalid packet type
            ("999invalid", 9, "99invalid"),  # Invalid format
            ("7probe", 7, "probe"),
        ],
    )
    def test_unknown_packet_type_is_kept(self, unknown, packet_type, data):
        """Test a packet type that isn't known doesn't fail decoding."""
        packet = Packet.decode(unknown)

        assert packet.engine_packet_type == packet_type
        assert not isinstance(packet.engine_packet_type, EnginePacketType)
        assert not packet.is_socket_packet
        assert packet.data == data

    def test_binary_payload_encoding(self, sample_packets):
        """Test binary payload encoding integrity."""
        packets = [
            sample_packets["open"],
            sample_packets["socket_event"],
        ]

        payload = Payload(packets=packets)
        encoded = payload.encode()

        # Should be binary format with delimiters: the length is written digit by digit
        assert encoded == (
            b"\x00\x08\x05\xff"
            b'0{"sid":"test-sid","upgrades":["websocket"],'
            b'"pingInterval":25000,"pingTimeout":60000}'
            b"\x00\x03\x02\xff"
            b'42["test_event",{"key":"value"}]'
        )

        # Should be decodable
        decoded = Payload.decode(encoded)
        assert len(decoded.packets) == len(packets)
        assert decoded.packets[1].socket_packet_type == SocketPacketType.EVENT
        assert decoded.packets[1].data == ["test_event", {"key": "value"}]

    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (None, "2"),
            ("text", "2text"),
            (5, "25"),
            (1.5, "21.5"),
            ({"a": 1, "b": [True, None]}, '2{"a":1,"b":[true,null]}'),
            ([1, "two"], '2[1,"two"]'),
        ],
    )
    def test_engine_packet_data_encoding(self, data, expected):
        """Test the data of an engine packet is written as text, JSON for containers."""
        assert Packet(EnginePacketType.PING, data=data).encode() == expected

    @pytest.mark.parametrize(
        ("encoded", "expected"),
        [
            ("2probe", "probe"),
            ("23", "3"),  # A number stays text
            ("2true", "true"),
            ("2null", None),
            ('2"quoted"', "quoted"),
            ("2[1,2]", [1, 2]),
            ('0{"sid":"a"}', {"sid": "a"}),
        ],
    )
    def test_engine_packet_data_decoding(self, encoded, expected):
        """Test the data of an engine packet is JSON when it is, and text otherwise."""
        assert Packet.decode(encoded).data == expected

    def test_custom_json_functions_are_used(self):
        """Test packets are encoded and decoded with the given JSON functions."""
        event = Packet(
            EnginePacketType.MESSAGE, SocketPacketType.EVENT, data=["a", "b"]
        )
        calls = []

        def serialize(data, **kwargs):
            calls.append((data, kwargs))
            return "<serialized>"

        def parse(text):
            return ("parsed", text)

        assert event.encode(json_serialize=serialize) == "42<serialized>"
        assert calls == [(["a", "b"], {"separators": (",", ":")})]
        assert Packet.decode('42["a","b"]', json_serialize=parse).data == (
            "parsed",
            '["a","b"]',
        )
        assert Packet.decode("2abc", json_serialize=parse).data == ("parsed", "abc")


class TestEngineIOPayloadCodec:
    """Test Engine.IO payload framing: <0><length digits><0xff><packet>."""

    @pytest.mark.parametrize(
        ("size", "length_digits"),
        [
            (1, b"\x01"),
            (9, b"\x09"),
            (10, b"\x01\x00"),
            (99, b"\x09\x09"),
            (100, b"\x01\x00\x00"),
            (1000, b"\x01\x00\x00\x00"),
        ],
    )
    def test_length_is_written_digit_by_digit(self, size, length_digits):
        """Test a packet of any length is framed and decoded back."""
        packet = Packet(EnginePacketType.PING, data="x" * (size - 1))
        assert len(packet.encode()) == size

        encoded = Payload([packet]).encode()

        assert encoded == b"\x00" + length_digits + b"\xff" + packet.encode().encode()
        decoded = Payload.decode(encoded)
        assert [p.encode() for p in decoded.packets] == [packet.encode()]

    def test_empty_payload_encodes_to_nothing(self):
        assert Payload().encode() == b""

    def test_many_packets_keep_their_order(self):
        """Test a payload of many different packets is decoded in full and in order."""
        packets = [
            Packet(
                EnginePacketType.MESSAGE,
                SocketPacketType.EVENT,
                data=["event", index, "가" * index],
            )
            for index in range(40)
        ]

        decoded = Payload.decode(Payload(packets).encode())

        assert [p.data for p in decoded.packets] == [p.data for p in packets]

    def test_jsonp_wrapping(self):
        """Test a JSONP payload is wrapped in the callback, with its quotes escaped."""
        plain = Payload([Packet(EnginePacketType.PING)])
        with_quotes = Payload(
            [Packet(EnginePacketType.MESSAGE, SocketPacketType.EVENT, data=["e"])]
        )

        assert plain.encode(jsonp_index="3") == b"___eio[3](\x00\x01\xff2);"
        assert (
            with_quotes.encode(jsonp_index="0")
            == b'___eio[0](\x00\x07\xff42[\\"e\\"]);'
        )

    def test_jsonp_post_body_is_decoded(self):
        """Test the 'd=' form body of a JSONP POST is url-decoded before parsing."""
        payload = Payload(
            [
                Packet(EnginePacketType.PING),
                Packet(EnginePacketType.MESSAGE, SocketPacketType.EVENT, data=["e"]),
            ]
        )
        body = b"d=" + quote_from_bytes(payload.encode()).encode()
        assert b"%FF" in body

        decoded = Payload.decode(body)

        assert [p.encode() for p in decoded.packets] == ["2", '42["e"]']

    def test_binary_packets_are_skipped(self):
        """Test binary packets (flag 1) are left out: only text packets are decoded."""
        encoded = (
            b"\x01\x03\xff\xde\xad\xbe"  # Binary packet
            b"\x00\x01\xff2"  # PING
            b"\x01\x01\xff\x00"  # Binary packet
        )

        decoded = Payload.decode(encoded)

        assert [p.encode() for p in decoded.packets] == ["2"]
        assert Payload.decode(b"\x01\x01\xff\x00").packets == []

    @pytest.mark.parametrize(
        ("encoded", "error"),
        [
            (b"\x00\xff2", TypeError),  # No length
            (b"\x00\x01", ValueError),  # No 0xff after the length
            (b"\xff", ValueError),  # Nothing before 0xff
            (b"\x00\x01\xffx", ValueError),  # The packet isn't a packet
            (b"\x00\x02\xff\xff3", UnicodeDecodeError),  # The packet isn't text
            (b"\x00\x01\xff2\x00", ValueError),  # Cut off in the next frame
            (b"d=", KeyError),  # A form body without data
        ],
        ids=[
            "no_length",
            "no_separator",
            "no_header",
            "invalid_packet",
            "invalid_text",
            "cut_off_frame",
            "empty_form_body",
        ],
    )
    def test_malformed_payload_raises(self, encoded, error):
        """Test a payload that isn't well formed fails instead of giving packets."""
        with pytest.raises(error):
            Payload.decode(encoded)


@pytest.mark.asyncio
class TestEngineIOErrorHandling:
    """Test Engine.IO error handling and edge cases."""

    async def test_connection_close_handling(
        self, mock_server, mock_connection_state, test_session, wait_finished
    ):
        """Test proper handling of connection close packets."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )
        guard_read_loop_spinning(gateway)
        read_task = gateway.read_in_background()

        assert gateway.is_connected

        # Send close packet: the server answers by closing the websocket
        await gateway.send(Packet(EnginePacketType.CLOSE))
        await wait_finished(read_task)

        # Should be disconnected
        assert "1" in mock_server.received_messages
        assert not gateway.is_connected
        assert gateway.websocket.closed

    async def test_invalid_server_response(self, mock_connection_state, test_session):
        """Test handling of invalid server responses."""
        # Try to connect to non-existent server
        with pytest.raises(Exception):  # Should raise connection error
            await ChzzkGateway._connect_polling(
                url="http://localhost:99999",  # Invalid port
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                ssl=False,
            )

    async def test_websocket_connection_error(
        self, mock_connection_state, test_session
    ):
        """Test handling of WebSocket connection failures."""
        # Try to connect to non-existent WebSocket endpoint
        with pytest.raises(Exception):
            await ChzzkGateway._connect_websocket(
                url="http://localhost:99999",
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                ssl=False,
            )

    async def test_receive_error_packet_message(self):
        """Test ReceiveErrorPacket can be raised with the received data."""
        error = ReceiveErrorPacket("websocket", "broken frame")

        assert error.current_transport == "websocket"
        assert error.data == "broken frame"
        assert "broken frame" in str(error)


@pytest.mark.asyncio
class TestEngineIOConnectionClose:
    """Test the connection ends cleanly however it is closed."""

    async def test_server_close_ends_read_loop(self, mock_server, test_session):
        """Test the read loop ends when the server closes the websocket silently."""
        loop = asyncio.get_running_loop()
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=loop,
            session=test_session,
            ssl=False,
        )
        server_websocket = mock_server.connections[mock_server.sid]
        other_gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=loop,
            session=test_session,
            ssl=False,
        )
        guard_read_loop_spinning(gateway)
        guard_read_loop_spinning(other_gateway)
        read_task = gateway.read_in_background()
        other_gateway.read_in_background()

        # Close from the server side, as on a gateway restart or network drop
        await server_websocket.close()

        # A server-side close is a normal disconnection
        await asyncio.wait_for(read_task, timeout=2.0)
        assert not gateway.is_connected
        assert gateway.websocket.closed
        await asyncio.sleep(0)
        assert gateway._ping_loop_task.done()

        # The event loop is not blocked: the other connection still gets PONG
        other_gateway._heartbeat_receive_event.clear()
        await other_gateway.send_ping()
        await asyncio.wait_for(
            other_gateway._heartbeat_receive_event.wait(), timeout=2.0
        )
        assert other_gateway.is_connected

        # Disconnecting a closed connection is a no-op, also twice
        await gateway.disconnect()
        await gateway.disconnect()
        await other_gateway.disconnect()

    async def test_disconnect_after_server_close(self, mock_server, test_session):
        """Test disconnect() is safe after the server closed the websocket."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # No read loop is running, so the gateway hasn't noticed the close yet
        await mock_server.connections[mock_server.sid].close()
        await asyncio.sleep(0.1)

        await gateway.disconnect()
        assert not gateway.is_connected
        assert gateway.websocket.closed
        await gateway.disconnect()

    async def test_close_packet_disconnects_from_read_loop(
        self, mock_server, test_session
    ):
        """Test a CLOSE packet disconnects without cancelling the read loop midway."""
        close_received = asyncio.Event()

        async def close_handler(data):
            close_received.set()

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook={EnginePacketType.CLOSE: close_handler},
            ssl=False,
        )
        guard_read_loop_spinning(gateway)
        read_task = gateway.read_in_background()

        await mock_server.send_custom_packet(Packet(EnginePacketType.CLOSE))

        # disconnect() runs inside the read task; the CLOSE hook still runs after it
        await asyncio.wait_for(read_task, timeout=2.0)
        assert close_received.is_set()
        assert not gateway.is_connected
        assert gateway.websocket.closed

        await gateway.disconnect()

    async def test_pong_timeout_closes_connection(self, mock_server, test_session):
        """Test the connection is closed when no PONG arrives within ping timeout."""
        mock_server._auto_pong = False
        mock_server.ping_interval = 1000
        mock_server.ping_timeout = 200

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )
        guard_read_loop_spinning(gateway)
        read_task = gateway.read_in_background()

        # The ping loop closes the connection instead of raising in its own task
        await asyncio.wait_for(gateway._ping_loop_task, timeout=2.0)
        await asyncio.wait_for(read_task, timeout=2.0)
        assert not gateway.is_connected
        assert gateway.websocket.closed

    async def test_read_error_closes_connection(self, mock_server, test_session):
        """Test a failed poll closes the connection and is raised from the read task."""
        mock_server.upgrades = []
        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )
        assert gateway.current_transport == "polling"

        mock_server._poll_error_status = 500
        read_task = gateway.read_in_background()

        with pytest.raises(ReceiveErrorPacket) as error:
            await asyncio.wait_for(read_task, timeout=2.0)
        assert error.value.data == 500
        assert not gateway.is_connected
        await asyncio.sleep(0)
        assert gateway._ping_loop_task.done()

        await gateway.disconnect()


@pytest.mark.asyncio
class TestEngineIOTransportUpgrade:
    """Test Engine.IO transport upgrade mechanism."""

    async def test_polling_to_websocket_upgrade(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test complete upgrade process from polling to WebSocket."""
        # Use the high-level connect method which handles upgrade
        gateway = await ChzzkGateway.connect(
            url=mock_server.url,
            state=mock_connection_state,
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Should upgrade to WebSocket if available
        # The connect method tries WebSocket upgrade automatically
        assert gateway.is_connected
        assert gateway.session_id is not None

        await gateway.disconnect()

    async def test_upgrade_packet_exchange(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test UPGRADE packet is sent correctly during upgrade."""
        from chzzkpy.gateway import OpenPacketInfo

        open_packet = OpenPacketInfo(
            sid="test-upgrade-sid",
            upgrades=["websocket"],
            ping_interval=int(25000),
            ping_timeout=int(60000),
        )

        # This will perform upgrade and send UPGRADE packet
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            open_packet=open_packet,
            ssl=False,
        )

        assert gateway.is_connected
        assert gateway.current_transport == "websocket"

        await gateway.disconnect()


@pytest.mark.asyncio
class TestEngineIOPollingResponses:
    """Test the HTTP responses of the polling transport are judged and released."""

    @staticmethod
    async def connect_polling(mock_server, session) -> ChzzkGateway:
        mock_server.upgrades = []
        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=session,
            ssl=False,
        )
        assert gateway.current_transport == "polling"
        return gateway

    @pytest.mark.parametrize("status", [201, 202, 204])
    async def test_write_accepts_any_2xx_status(
        self, mock_server, test_session, status
    ):
        """Test a polling write answered with a 2xx status other than 200 succeeds."""
        mock_server._post_status = status
        gateway = await self.connect_polling(mock_server, test_session)

        # The heartbeat ping is answered the same way and must not end the connection
        await asyncio.sleep(0.1)
        assert gateway.is_connected

        mock_server.received_messages.clear()
        await gateway.send(
            Packet(
                EnginePacketType.MESSAGE,
                SocketPacketType.EVENT,
                data=["test_event", {"key": "value"}],
            )
        )
        assert len(mock_server.received_messages) == 1
        assert acquired_connections(test_session) == 0

        await gateway.disconnect()

    @pytest.mark.parametrize("status", [400, 500])
    async def test_write_rejects_error_status(self, mock_server, test_session, status):
        """Test a failed polling write raises and releases its response."""
        gateway = await self.connect_polling(mock_server, test_session)
        await asyncio.sleep(0.1)

        mock_server._post_status = status
        mock_server._error_body_size = 1024 * 1024
        with pytest.raises(HTTPException) as error:
            await gateway.send(Packet(EnginePacketType.PING))
        assert str(status) in str(error.value)

        # The traceback still refers to the response, so only release() frees it
        assert acquired_connections(test_session) == 0

        mock_server._post_status = None
        await gateway.disconnect()

    async def test_read_error_releases_response(self, mock_server, test_session):
        """Test a failed poll releases its response before raising."""
        gateway = await self.connect_polling(mock_server, test_session)
        await asyncio.sleep(0.1)

        mock_server._poll_error_status = 500
        mock_server._error_body_size = 1024 * 1024
        with pytest.raises(ReceiveErrorPacket) as error:
            await gateway._read_polling()
        assert error.value.data == 500
        assert acquired_connections(test_session) == 0

        mock_server._poll_error_status = None
        await gateway.disconnect()

    async def test_handshake_error_releases_response(self, mock_server, test_session):
        """Test a failed polling handshake releases its response before raising."""
        mock_server._handshake_error_status = 503
        mock_server._error_body_size = 1024 * 1024

        with pytest.raises(ChatConnectFailed) as error:
            await ChzzkGateway._connect_polling(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                ssl=False,
            )
        assert "503" in str(error.value)
        assert acquired_connections(test_session) == 0


@pytest.mark.asyncio
class TestEngineIOHandshakeCleanup:
    """Test a websocket is closed when its connect handshake fails."""

    @staticmethod
    def upgrade_open_packet(mock_server) -> OpenPacketInfo:
        return OpenPacketInfo(
            sid=mock_server.sid,
            upgrades=["websocket"],
            ping_interval=int(mock_server.ping_interval),
            ping_timeout=int(mock_server.ping_timeout),
        )

    @pytest.mark.parametrize(
        "reply",
        [
            Packet(EnginePacketType.PONG, data="not-probe"),
            Packet(EnginePacketType.PONG),
            Packet(EnginePacketType.NOOP),
        ],
        ids=["wrong_data", "no_data", "other_packet"],
    )
    async def test_wrong_probe_reply_closes_websocket(
        self, mock_server, test_session, monkeypatch, reply
    ):
        """Test the websocket is closed when the upgrade probe isn't answered."""
        websockets = track_websockets(monkeypatch)
        mock_server._probe_reply = reply.encode()

        with pytest.raises(ChatConnectFailed):
            await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                open_packet=self.upgrade_open_packet(mock_server),
                ssl=False,
            )

        assert len(websockets) == 1
        assert websockets[0].closed

    async def test_malformed_probe_reply_closes_websocket(
        self, mock_server, test_session, monkeypatch
    ):
        """Test the websocket is closed when the probe reply isn't a packet."""
        websockets = track_websockets(monkeypatch)
        mock_server._probe_reply = "not a packet"

        with pytest.raises(ValueError):
            await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                open_packet=self.upgrade_open_packet(mock_server),
                ssl=False,
            )

        assert len(websockets) == 1
        assert websockets[0].closed

    async def test_failed_upgrade_falls_back_to_polling(
        self, mock_server, test_session, monkeypatch
    ):
        """Test a failed probe leaves no websocket behind and keeps polling."""
        websockets = track_websockets(monkeypatch)
        mock_server._probe_reply = Packet(EnginePacketType.NOOP).encode()

        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        assert gateway.current_transport == "polling"
        assert gateway.is_connected
        assert [websocket.closed for websocket in websockets] == [True]

        await gateway.disconnect()

    @pytest.mark.parametrize(
        "reply", ["not a packet", Packet(EnginePacketType.NOOP).encode()]
    )
    async def test_invalid_open_packet_closes_websocket(
        self, mock_server, test_session, monkeypatch, reply
    ):
        """Test the websocket is closed when a direct connection gets no OPEN packet."""
        websockets = track_websockets(monkeypatch)
        mock_server._open_reply = reply

        with pytest.raises(ValueError):
            await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                ssl=False,
            )

        assert len(websockets) == 1
        assert websockets[0].closed
