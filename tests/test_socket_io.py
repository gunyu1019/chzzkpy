"""MIT License

Copyright (c) 2024-2025 gunyu1019

Socket.IO protocol layer tests.
Tests event routing, data transmission, and high-level communication.
"""

import json

import pytest
import asyncio
import aiohttp
from chzzkpy.gateway import ChzzkGateway
from chzzkpy.packet import Packet
from chzzkpy.payload import Payload
from chzzkpy.enums import EnginePacketType, SocketPacketType
from chzzkpy.state import ConnectionState


@pytest.mark.asyncio
class TestSocketIOConnection:
    """Test Socket.IO connection and handshake."""

    async def test_socket_connect_event(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test Socket.IO CONNECT packet is received on connection."""
        connects = []

        async def connect_handler(data):
            connects.append(data)

        # Set up handler for CONNECT packet
        event_hook = {
            SocketPacketType.CONNECT: connect_handler,
        }

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )
        # The server sends CONNECT after OPEN: it is read, it isn't part of the connect
        assert connects == []
        gateway.read_in_background()

        await wait_until(lambda: connects, message="the CONNECT packet")
        assert connects == [None]
        assert gateway.is_connected
        await gateway.disconnect()

    async def test_socket_disconnect_event(
        self,
        mock_server,
        mock_connection_state,
        test_session,
        wait_until,
        wait_finished,
    ):
        """Test Socket.IO DISCONNECT packet handling."""
        disconnects = []

        async def disconnect_handler(data):
            disconnects.append(data)

        event_hook = {
            SocketPacketType.DISCONNECT: disconnect_handler,
        }

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )

        # Start background reading
        read_task = gateway.read_in_background()

        # A DISCONNECT from the server reaches the hook
        await mock_server.send_custom_packet(
            Packet(EnginePacketType.MESSAGE, SocketPacketType.DISCONNECT)
        )
        await wait_until(lambda: disconnects, message="the DISCONNECT packet")
        assert disconnects == [None]

        # Send disconnect: the server answers with CLOSE and closes the websocket
        await gateway.send_disconnet()
        await wait_finished(read_task)
        assert "41" in mock_server.received_messages
        assert not gateway.is_connected

        await gateway.disconnect()


@pytest.mark.asyncio
class TestSocketIOEvents:
    """Test Socket.IO event emission and reception."""

    async def test_emit_event(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test emitting custom events to server."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Emit a custom event
        event_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["custom_event", {"message": "hello", "value": 42}],
        )
        await gateway.send(event_packet)

        # Verify server received the event, with its data intact
        await wait_until(lambda: mock_server.emit_events, message="the event")
        assert mock_server.emit_events == [
            ("custom_event", ["custom_event", {"message": "hello", "value": 42}])
        ]
        assert (
            mock_server.received_messages.count(
                '42["custom_event",{"message":"hello","value":42}]'
            )
            == 1
        )

        await gateway.disconnect()

    async def test_receive_event(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test receiving custom events from server."""
        received_events = []

        async def event_handler(data):
            received_events.append(data)

        event_hook = {
            SocketPacketType.EVENT: event_handler,
        }

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )

        # Start background reading to receive events
        gateway.read_in_background()

        # Server sends event to client
        await mock_server.broadcast_event("server_event", {"data": "test_value"})

        # Verify event was received: the name and the data stay together
        await wait_until(lambda: received_events, message="the event")
        assert received_events == [["server_event", {"data": "test_value"}]]

        await gateway.disconnect()

    async def test_event_with_multiple_arguments(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test events with multiple data arguments."""
        received_events = []

        async def event_handler(data):
            received_events.append(data)

        event_hook = {
            SocketPacketType.EVENT: event_handler,
        }

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )

        # Send event with multiple arguments
        event_data = [
            "multi_arg_event",
            {"arg1": "value1"},
            {"arg2": "value2"},
            [1, 2, 3],
        ]
        event_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=event_data,
        )
        await gateway.send(event_packet)

        # Verify server received all arguments, in order
        await wait_until(lambda: mock_server.emit_events, message="the event")
        assert mock_server.emit_events == [("multi_arg_event", event_data)]
        assert (
            mock_server.received_messages.count(
                '42["multi_arg_event",{"arg1":"value1"},{"arg2":"value2"},[1,2,3]]'
            )
            == 1
        )

        await gateway.disconnect()


@pytest.mark.asyncio
class TestSocketIOAcknowledgments:
    """Test Socket.IO acknowledgment (ACK) mechanism."""

    async def test_send_event_with_ack_request(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test sending event that requests acknowledgment."""
        ack_received = asyncio.Event()

        async def ack_handler(data):
            ack_received.set()

        event_hook = {
            SocketPacketType.ACK: ack_handler,
        }

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )
        gateway.read_in_background()

        # Send event with packet ID (requests ACK)
        event_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["ack_event", {"data": "test"}],
            packet_id=123,
        )
        await gateway.send(event_packet)

        # Wait for ACK
        try:
            await asyncio.wait_for(ack_received.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("ACK not received within timeout")

        # The packet id went out with the event
        assert (
            mock_server.received_messages.count('42123["ack_event",{"data":"test"}]')
            == 1
        )

        await gateway.disconnect()

    async def test_auto_ack_on_receive(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test automatic ACK sending when receiving event with ID."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )
        gateway.read_in_background()

        # Server sends event with ID, client should auto-ACK
        event_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["test_event", {"data": "value"}],
            packet_id=456,
        )
        await mock_server.send_custom_packet(event_packet)

        # The gateway should have automatically sent an ACK (a socket.io packet of
        # type 3), once. Its packet id is checked in test_gateway_errors.py.
        def acks():
            return [m for m in mock_server.received_messages if m.startswith("43")]

        await wait_until(acks, message="the ACK")
        assert len(acks()) == 1
        assert gateway.is_connected

        await gateway.disconnect()


@pytest.mark.asyncio
class TestSocketIOStateIntegration:
    """Test Socket.IO integration with ConnectionState."""

    async def test_state_event_dispatching(self, mock_server, test_session, wait_until):
        """Test that events are properly dispatched through ConnectionState."""
        dispatched_events = []

        def mock_dispatch(event: str, *args, **kwargs):
            dispatched_events.append((event, args, kwargs))

        state = ConnectionState(
            dispatch=mock_dispatch,
            handler={},
            http=None,
            debug_mode=True,
        )

        # Use direct websocket connection to avoid polling timeout
        event_hook = {}
        for event, parsing_func in state.gateway_parsers.items():
            if parsing_func is not None:
                event_hook[event] = parsing_func

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )

        # The OPEN packet is part of the connect, the socket.io CONNECT is read after it
        assert dispatched_events == [("engine_connect", (mock_server.sid,), {})]
        gateway.read_in_background()
        await wait_until(
            lambda: ("socket_connect", (), {}) in dispatched_events,
            message="the socket_connect event",
        )

        # Should have dispatched engine_connect and socket_connect events, once each
        assert dispatched_events == [
            ("engine_connect", (mock_server.sid,), {}),
            ("socket_connect", (), {}),
        ]

        await gateway.disconnect()

    async def test_state_custom_event_parsing(self, mock_server, test_session):
        """Test custom event parsing through ConnectionState."""
        test_event_received = asyncio.Event()
        received_data = {}

        def mock_dispatch(event: str, *args, **kwargs):
            if event == "socket_event":
                received_data["event"] = args[0] if args else None
                received_data["data"] = args[1:] if len(args) > 1 else None
                if args and args[0] == "test_custom_event":
                    test_event_received.set()

        state = ConnectionState(
            dispatch=mock_dispatch,
            handler={},
            http=None,
            debug_mode=True,
        )

        # Use direct websocket connection to avoid polling timeout
        event_hook = {}
        for event, parsing_func in state.gateway_parsers.items():
            if parsing_func is not None:
                event_hook[event] = parsing_func

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )

        # Start background reading to receive events
        gateway.read_in_background()

        # Server broadcasts event
        await mock_server.broadcast_event(
            "test_custom_event",
            {"key": "value", "number": 123},
        )

        # Wait for event
        try:
            await asyncio.wait_for(test_event_received.wait(), timeout=2.0)
            assert True, "Custom event received through state"
        except asyncio.TimeoutError:
            pytest.fail("Custom event not received")

        await gateway.disconnect()


@pytest.mark.asyncio
class TestSocketIOPayloadDeserialization:
    """Test Socket.IO payload deserialization."""

    async def test_json_payload_parsing(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test JSON payload is correctly deserialized."""
        received_payloads = []

        async def event_handler(data):
            received_payloads.append(data)

        event_hook = {
            SocketPacketType.EVENT: event_handler,
        }

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )

        # Start background reading
        gateway.read_in_background()

        # Send complex JSON payload
        complex_data = {
            "string": "test",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "array": [1, 2, 3],
            "nested": {"key": "value"},
        }

        await mock_server.broadcast_event("complex_event", complex_data)
        await wait_until(lambda: received_payloads, message="the event")

        # Verify payload was deserialized correctly, each value with its JSON type
        assert received_payloads == [["complex_event", complex_data]]
        received = received_payloads[0][1]
        assert type(received["number"]) is int
        assert type(received["float"]) is float
        assert received["boolean"] is True
        assert received["null"] is None
        assert received["array"] == [1, 2, 3]
        assert received["nested"] == {"key": "value"}

        await gateway.disconnect()

    @pytest.mark.parametrize(
        ("event_name", "event_data", "frame"),
        [
            ("string_event", "simple string", '42["string_event","simple string"]'),
            ("number_event", 12345, '42["number_event",12345]'),
            ("float_event", 123.456, '42["float_event",123.456]'),
            ("boolean_event", True, '42["boolean_event",true]'),
            (
                "array_event",
                [1, "two", 3.0, True, None],
                '42["array_event",[1,"two",3.0,true,null]]',
            ),
            (
                "object_event",
                {"key1": "value1", "key2": 42},
                '42["object_event",{"key1":"value1","key2":42}]',
            ),
            (
                "unicode_event",
                "안녕 👋",
                '42["unicode_event","\\uc548\\ub155 \\ud83d\\udc4b"]',
            ),
        ],
    )
    async def test_event_data_type_integrity(
        self,
        mock_server,
        mock_connection_state,
        test_session,
        wait_until,
        event_name,
        event_data,
        frame,
    ):
        """Test that data types are preserved during serialization/deserialization."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Send event
        event_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=[event_name, event_data],
        )
        await gateway.send(event_packet)
        await wait_until(lambda: mock_server.emit_events, message="the event")

        # Verify server received correct data type: the frame tells 3.0 from 3
        assert mock_server.received_messages.count(frame) == 1
        assert mock_server.emit_events == [(event_name, [event_name, event_data])]
        received = mock_server.emit_events[0][1][1]
        assert type(received) is type(event_data)

        await gateway.disconnect()


@pytest.mark.asyncio
class TestSocketIOBroadcast:
    """Test Socket.IO broadcast and room functionality."""

    async def test_broadcast_to_multiple_clients(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test server can broadcast to multiple connected clients."""
        clients = []
        received_counts = []

        # Connect multiple clients
        for i in range(3):
            received_events = []

            async def event_handler(data, events_list=received_events):
                events_list.append(data)

            event_hook = {
                SocketPacketType.EVENT: event_handler,
            }

            gateway = await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                event_hook=event_hook,
                ssl=False,
            )

            # Start background reading for each client
            gateway.read_in_background()

            clients.append((gateway, received_events))

        # Broadcast event from server
        await mock_server.broadcast_event("broadcast_test", {"msg": "hello all"})
        await wait_until(
            lambda: all(received_events for _, received_events in clients),
            message="every client to receive the broadcast",
        )

        # All clients should receive the broadcast, once
        for gateway, received_events in clients:
            received_counts.append(len(received_events))
            assert received_events == [["broadcast_test", {"msg": "hello all"}]]
            await gateway.disconnect()

        assert received_counts == [1, 1, 1]


@pytest.mark.asyncio
class TestSocketIOReconnection:
    """Test Socket.IO reconnection behavior."""

    async def test_connection_recovery_after_close(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test client can reconnect after connection is closed."""
        # First connection
        gateway1 = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        assert gateway1.is_connected
        first_sid = gateway1.session_id

        # Disconnect
        await gateway1.disconnect()
        assert not gateway1.is_connected

        # Reconnect
        gateway2 = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        assert gateway2.is_connected
        # Should get new session ID
        assert gateway2.session_id is not None

        await gateway2.disconnect()


@pytest.mark.asyncio
class TestSocketIOErrorHandling:
    """Test Socket.IO error handling."""

    async def test_connect_error_packet(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test handling of CONNECT_ERROR packet."""
        errors = []

        async def error_handler(data):
            errors.append(data)

        event_hook = {
            SocketPacketType.CONNECT_ERROR: error_handler,
        }

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )

        gateway.read_in_background()

        # Server sends connect error
        error_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.CONNECT_ERROR,
            data={"message": "Authentication failed"},
        )
        await mock_server.send_custom_packet(error_packet)

        await wait_until(lambda: errors, message="the CONNECT_ERROR packet")
        assert errors == [{"message": "Authentication failed"}]

        await gateway.disconnect()

    async def test_invalid_event_handling(
        self, mock_server, mock_connection_state, test_session, wait_until
    ):
        """Test handling of malformed event packets."""
        received_events = []

        async def event_handler(data):
            received_events.append(data)

        event_hook = {
            SocketPacketType.EVENT: event_handler,
        }

        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook=event_hook,
            ssl=False,
        )

        # Send malformed event (not a list)
        malformed_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data="not_a_list",  # Should be a list
        )

        await gateway.send(malformed_packet)

        # Sending it is not an error: the server takes it as an event of no name
        await wait_until(lambda: mock_server.emit_events, message="the event")
        assert mock_server.emit_events == [("unknown", "not_a_list")]
        assert mock_server.received_messages.count('42"not_a_list"') == 1

        # Receiving it is not an error either: the hook gets the data as it is
        gateway.read_in_background()
        await mock_server.send_text('42"not_a_list"')
        await wait_until(lambda: received_events, message="the received event")
        assert received_events == ["not_a_list"]
        assert gateway.is_connected

        await gateway.disconnect()


class TestSocketIONamespaces:
    """Test Socket.IO namespace support."""

    def test_packet_with_namespace(self):
        """Test creating and encoding packets with namespaces."""
        packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["test_event", {"data": "value"}],
            namespace="/custom-namespace",
        )

        # Encode
        encoded = packet.encode()
        assert "/custom-namespace" in encoded

        # Decode
        decoded = Packet.decode(encoded)
        assert decoded.namespace == "/custom-namespace"
        assert decoded.socket_packet_type == SocketPacketType.EVENT

    def test_namespace_with_query_params(self):
        """Test namespace with query parameters."""
        # Create packet
        test_packet_str = '42/namespace?token=abc123,0["event",{}]'

        # Decode
        decoded = Packet.decode(test_packet_str)

        # Namespace should be parsed without query params
        assert decoded.namespace == "/namespace"
        assert decoded.socket_packet_type == SocketPacketType.EVENT


EMPTY = object()  # Neither None nor "" matters for a packet without data


class TestSocketIOPacketCodec:
    """Test Socket.IO packet encoding/decoding: namespaces, packet ids and data."""

    @pytest.mark.parametrize(
        ("encoded", "packet_type", "namespace", "packet_id", "data"),
        [
            ("40", SocketPacketType.CONNECT, None, None, EMPTY),
            ("40/admin", SocketPacketType.CONNECT, "/admin", None, EMPTY),
            ("40/admin,", SocketPacketType.CONNECT, "/admin", None, EMPTY),
            ("40/admin?token=abc", SocketPacketType.CONNECT, "/admin", None, EMPTY),
            ("41/admin,", SocketPacketType.DISCONNECT, "/admin", None, EMPTY),
            ("42", SocketPacketType.EVENT, None, None, EMPTY),
            ('42["e"]', SocketPacketType.EVENT, None, None, ["e"]),
            ('42/admin,["e",1]', SocketPacketType.EVENT, "/admin", None, ["e", 1]),
            ('42/admin?x=1,["e"]', SocketPacketType.EVENT, "/admin", None, ["e"]),
            ('42/admin,0["e"]', SocketPacketType.EVENT, "/admin", 0, ["e"]),
            ('420["e",{"k":"v"}]', SocketPacketType.EVENT, None, 0, ["e", {"k": "v"}]),
            ('42["a-b",-1]', SocketPacketType.EVENT, None, None, ["a-b", -1]),
            ("43", SocketPacketType.ACK, None, None, EMPTY),
            ('430["ok"]', SocketPacketType.ACK, None, 0, ["ok"]),
            (
                '44{"message":"denied"}',
                SocketPacketType.CONNECT_ERROR,
                None,
                None,
                {"message": "denied"},
            ),
            (
                '451-["e",{"_placeholder":true,"num":0}]',
                SocketPacketType.BINARY_EVENT,
                None,
                None,
                ["e", {"_placeholder": True, "num": 0}],
            ),
            (
                '461-/admin,["ok",{"_placeholder":true,"num":0}]',
                SocketPacketType.BINARY_ACK,
                "/admin",
                None,
                ["ok", {"_placeholder": True, "num": 0}],
            ),
        ],
    )
    def test_decode(self, encoded, packet_type, namespace, packet_id, data):
        """Test every part of a socket.io packet is decoded."""
        packet = Packet.decode(encoded)

        assert packet.engine_packet_type == EnginePacketType.MESSAGE
        assert packet.socket_packet_type == packet_type
        assert packet.is_socket_packet
        assert packet.namespace == namespace
        assert packet.id == packet_id
        if data is EMPTY:
            assert not packet.data
        else:
            assert packet.data == data

    def test_decode_unknown_socket_packet_type(self):
        """Test a socket.io packet type that isn't known is kept as it is."""
        packet = Packet.decode('47["e"]')

        assert packet.socket_packet_type == 7
        assert not isinstance(packet.socket_packet_type, SocketPacketType)
        assert packet.data == ["e"]

    @pytest.mark.parametrize(
        ("encoded", "error"),
        [
            ("4a", ValueError),  # The type isn't a number
            ("4-1", ValueError),
            ('42-["a"]', json.JSONDecodeError),  # Not an attachment count
            ("42/admin,x", json.JSONDecodeError),  # The data isn't JSON
            ('42/admin,0["e"', json.JSONDecodeError),  # Cut off data
            ("42[1,]", json.JSONDecodeError),
        ],
    )
    def test_decode_malformed(self, encoded, error):
        """Test a socket.io packet whose data can't be read raises."""
        with pytest.raises(error):
            Packet.decode(encoded)

    @pytest.mark.parametrize(
        ("packet", "encoded"),
        [
            (Packet(EnginePacketType.MESSAGE, SocketPacketType.CONNECT), "40"),
            (
                Packet(
                    EnginePacketType.MESSAGE,
                    SocketPacketType.CONNECT,
                    namespace="/admin",
                ),
                "40/admin,",
            ),
            (Packet(EnginePacketType.MESSAGE, SocketPacketType.DISCONNECT), "41"),
            (Packet(EnginePacketType.MESSAGE, SocketPacketType.EVENT), "42"),
            (
                Packet(
                    EnginePacketType.MESSAGE,
                    SocketPacketType.EVENT,
                    data=["e", {"k": [1, None]}],
                    packet_id=12,
                    namespace="/ns",
                ),
                '42/ns,12["e",{"k":[1,null]}]',
            ),
            (
                Packet(EnginePacketType.MESSAGE, SocketPacketType.ACK, packet_id=0),
                "430",
            ),
            (
                Packet(
                    EnginePacketType.MESSAGE,
                    SocketPacketType.ACK,
                    data=["ok"],
                    packet_id=3,
                ),
                '433["ok"]',
            ),
            (
                Packet(
                    EnginePacketType.MESSAGE,
                    SocketPacketType.EVENT,
                    data=["chat", "안녕"],
                ),
                '42["chat","\\uc548\\ub155"]',
            ),
        ],
    )
    def test_encode(self, packet, encoded):
        """Test every part of a socket.io packet is encoded, without extra spaces."""
        assert packet.encode() == encoded

    @pytest.mark.parametrize("namespace", [None, "/admin"])
    def test_non_ascii_data_round_trip(self, namespace):
        """Test text outside ASCII is escaped when encoded and restored when decoded."""
        packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["chat", {"nickname": "치지직", "content": "안녕하세요 👋"}],
            namespace=namespace,
        )

        encoded = packet.encode()
        decoded = Packet.decode(encoded)

        assert encoded.isascii()
        assert decoded.data == packet.data
        assert decoded.namespace == namespace
        assert decoded.encode() == encoded
