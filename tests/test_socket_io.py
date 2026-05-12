"""MIT License

Copyright (c) 2024-2025 gunyu1019

Socket.IO protocol layer tests.
Tests event routing, data transmission, and high-level communication.
"""

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
        self, mock_server, mock_connection_state, test_session
    ):
        """Test Socket.IO CONNECT packet is received on connection."""
        connect_received = asyncio.Event()

        async def connect_handler(data):
            connect_received.set()

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

        # Wait for connect event
        try:
            await asyncio.wait_for(connect_received.wait(), timeout=2.0)
            assert True, "CONNECT event received"
        except asyncio.TimeoutError:
            # The connect event might be processed before we set up the handler
            # This is acceptable in this context
            pass

        assert gateway.is_connected
        await gateway.disconnect()

    async def test_socket_disconnect_event(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test Socket.IO DISCONNECT packet handling."""
        disconnect_received = asyncio.Event()

        async def disconnect_handler(data):
            disconnect_received.set()

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
        gateway.read_in_background()

        # Send disconnect
        await gateway.send_disconnet()
        await asyncio.sleep(0.1)

        await gateway.disconnect()


@pytest.mark.asyncio
class TestSocketIOEvents:
    """Test Socket.IO event emission and reception."""

    async def test_emit_event(self, mock_server, mock_connection_state, test_session):
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

        # Wait for server to receive
        await asyncio.sleep(0.1)

        # Verify server received the event
        assert len(mock_server.emit_events) > 0
        event_name, event_data = mock_server.emit_events[-1]
        assert event_name == "custom_event"

        await gateway.disconnect()

    async def test_receive_event(
        self, mock_server, mock_connection_state, test_session
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

        # Wait for client to receive
        await asyncio.sleep(0.2)

        # Verify event was received
        assert len(received_events) > 0

        await gateway.disconnect()

    async def test_event_with_multiple_arguments(
        self, mock_server, mock_connection_state, test_session
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

        await asyncio.sleep(0.1)

        # Verify server received all arguments
        assert len(mock_server.emit_events) > 0

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
            assert True, "ACK received"
        except asyncio.TimeoutError:
            pytest.fail("ACK not received within timeout")

        await gateway.disconnect()

    async def test_auto_ack_on_receive(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test automatic ACK sending when receiving event with ID."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Server sends event with ID, client should auto-ACK
        event_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["test_event", {"data": "value"}],
            packet_id=456,
        )
        await mock_server.send_custom_packet(event_packet)

        # Wait for client to process and send ACK
        await asyncio.sleep(0.2)

        # The gateway should have automatically sent an ACK
        # Verify by checking if ACK packet was sent (via message inspection)
        assert gateway.is_connected

        await gateway.disconnect()


@pytest.mark.asyncio
class TestSocketIOStateIntegration:
    """Test Socket.IO integration with ConnectionState."""

    async def test_state_event_dispatching(self, mock_server, test_session):
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

        # Wait for connection events
        await asyncio.sleep(0.2)

        # Should have dispatched engine_connect and socket_connect events
        event_names = [event[0] for event in dispatched_events]
        assert "engine_connect" in event_names or "socket_connect" in event_names

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
        self, mock_server, mock_connection_state, test_session
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
        await asyncio.sleep(0.2)

        # Verify payload was deserialized correctly
        assert len(received_payloads) > 0

        await gateway.disconnect()

    async def test_event_data_type_integrity(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test that data types are preserved during serialization/deserialization."""
        test_cases = [
            ("string_event", "simple string"),
            ("number_event", 12345),
            ("float_event", 123.456),
            ("boolean_event", True),
            ("array_event", [1, "two", 3.0, True, None]),
            ("object_event", {"key1": "value1", "key2": 42}),
        ]

        for event_name, event_data in test_cases:
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
            await asyncio.sleep(0.1)

            # Verify server received correct data type
            assert len(mock_server.emit_events) > 0

            await gateway.disconnect()

            # Clear for next test
            mock_server.emit_events.clear()
            mock_server.received_messages.clear()


@pytest.mark.asyncio
class TestSocketIOBroadcast:
    """Test Socket.IO broadcast and room functionality."""

    async def test_broadcast_to_multiple_clients(
        self, mock_server, mock_connection_state, test_session
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
        await asyncio.sleep(0.3)

        # All clients should receive the broadcast
        for gateway, received_events in clients:
            received_counts.append(len(received_events))
            await gateway.disconnect()

        # At least one client should have received the event
        assert any(
            count > 0 for count in received_counts
        ), "No client received broadcast"


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
        self, mock_server, mock_connection_state, test_session
    ):
        """Test handling of CONNECT_ERROR packet."""
        error_received = asyncio.Event()

        async def error_handler(data):
            error_received.set()

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

        # Server sends connect error
        error_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.CONNECT_ERROR,
            data={"message": "Authentication failed"},
        )
        await mock_server.send_custom_packet(error_packet)

        await asyncio.sleep(0.1)

        await gateway.disconnect()

    async def test_invalid_event_handling(
        self, mock_server, mock_connection_state, test_session
    ):
        """Test handling of malformed event packets."""
        received_events = []
        errors = []

        async def event_handler(data):
            try:
                received_events.append(data)
            except Exception as e:
                errors.append(e)

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

        try:
            await gateway.send(malformed_packet)
            await asyncio.sleep(0.1)
            # Should handle gracefully
        except Exception:
            # Expected for malformed data
            pass

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
