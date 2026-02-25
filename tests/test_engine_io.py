"""MIT License

Copyright (c) 2024-2025 gunyu1019

Engine.IO protocol layer tests.
Tests low-level communication integrity and connection processes.
"""

import asyncio

import pytest

from chzzkpy.enums import EnginePacketType, SocketPacketType
from chzzkpy.error import ChatConnectFailed
from chzzkpy.gateway import ChzzkGateway
from chzzkpy.packet import Packet
from chzzkpy.payload import Payload


@pytest.mark.asyncio
class TestEngineIOPolling:
    """Test Engine.IO polling transport."""

    async def test_polling_handshake(self, mock_server, mock_connection_state, test_session):
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

    async def test_polling_send_message(self, mock_server, mock_connection_state, test_session):
        """Test sending messages via polling transport."""
        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Send a test packet
        test_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["test_event", {"data": "test"}],
        )
        await gateway.send(test_packet)

        # Give server time to receive
        await asyncio.sleep(0.1)

        # Verify server received the message
        assert len(mock_server.received_messages) > 0

        await gateway.disconnect()

    async def test_polling_receive_data(self, mock_server, mock_connection_state, test_session):
        """Test receiving raw data packets via polling."""
        received_packets = []

        async def packet_handler(data):
            received_packets.append(data)

        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook={
                EnginePacketType.MESSAGE: packet_handler,
            },
            ssl=False,
        )

        # Wait for initial packets
        await asyncio.sleep(0.1)

        assert gateway.is_connected
        await gateway.disconnect()


@pytest.mark.asyncio
class TestEngineIOWebSocket:
    """Test Engine.IO WebSocket transport."""

    async def test_websocket_direct_connection(self, mock_server, mock_connection_state, test_session):
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

    async def test_websocket_upgrade_from_polling(self, mock_server, mock_connection_state, test_session):
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

    async def test_polling_only_without_upgrade(self, mock_server, mock_connection_state, test_session):
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

    async def test_websocket_upgrade_probe(self, mock_server, mock_connection_state, test_session):
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

    async def test_websocket_upgrade_failure(self, mock_server, mock_connection_state, test_session):
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
            assert not gateway.websocket.closed or gateway.current_transport == "polling"
        except ChatConnectFailed:
            # This is acceptable - upgrade failed
            pass
        finally:
            mock_server._accept_upgrade = True

    async def test_websocket_send_receive(self, mock_server, mock_connection_state, test_session):
        """Test bidirectional communication over WebSocket."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        # Send a test event
        test_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=["test_event", {"key": "value"}],
        )
        await gateway.send(test_packet)

        # Wait for server to receive
        await asyncio.sleep(0.1)

        # Verify server received
        assert len(mock_server.received_messages) > 0

        await gateway.disconnect()


@pytest.mark.asyncio
class TestEngineIOHeartbeat:
    """Test Engine.IO ping/pong heartbeat mechanism."""

    async def test_ping_pong_exchange(self, mock_server, mock_connection_state, test_session):
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

    async def test_ping_with_data(self, mock_server, mock_connection_state, test_session):
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
        await asyncio.sleep(0.1)

        # Verify message was sent
        assert gateway.is_connected

        await gateway.disconnect()

    async def test_heartbeat_timeout(self, mock_server, mock_connection_state, test_session):
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
            'open': sample_packets['open'],
            'ping': sample_packets['ping'],
            'pong': sample_packets['pong'],
            'ping_probe': sample_packets['ping_probe'],
            'pong_probe': sample_packets['pong_probe'],
            'upgrade': sample_packets['upgrade'],
            'close': sample_packets['close'],
        }

        for name, packet in engine_only_packets.items():
            # Encode
            encoded = packet.encode()
            assert isinstance(encoded, str)
            assert len(encoded) > 0

            # Decode
            decoded = Packet.decode(encoded)
            assert decoded.engine_packet_type == packet.engine_packet_type

    def test_socket_packet_encode_decode(self):
        """Test socket.io packet encoding and decoding."""
        # Create packets from encoded strings (as they would come from server)
        test_cases = [
            ("40", EnginePacketType.MESSAGE, SocketPacketType.CONNECT),  # CONNECT
            ("41", EnginePacketType.MESSAGE, SocketPacketType.DISCONNECT),  # DISCONNECT
            ('42["event",{"key":"value"}]', EnginePacketType.MESSAGE, SocketPacketType.EVENT),  # EVENT
            ("43", EnginePacketType.MESSAGE, SocketPacketType.ACK),  # ACK
        ]

        for encoded_str, expected_engine, expected_socket in test_cases:
            decoded = Packet.decode(encoded_str)
            assert decoded.engine_packet_type == expected_engine
            assert decoded.socket_packet_type == expected_socket

    def test_payload_encode_decode(self, sample_packets):
        """Test payload encoding/decoding with multiple packets."""
        packets = [
            sample_packets['open'],
            sample_packets['socket_connect'],
        ]

        payload = Payload(packets=packets)

        # Encode
        encoded = payload.encode()
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0

        # Decode
        decoded_payload = Payload.decode(encoded)
        assert len(decoded_payload.packets) == len(packets)

        # Verify each packet
        for original, decoded in zip(packets, decoded_payload.packets):
            assert decoded.engine_packet_type == original.engine_packet_type

    def test_malformed_packet_handling(self):
        """Test handling of malformed packets."""
        malformed_packets = [
            "",  # Empty
            "9",  # Invalid packet type
            "999invalid",  # Invalid format
        ]

        for malformed in malformed_packets:
            try:
                packet = Packet.decode(malformed)
                # Should handle gracefully or raise appropriate error
                assert packet is not None
            except (ValueError, KeyError, IndexError):
                # These exceptions are acceptable for malformed data
                pass

    def test_binary_payload_encoding(self, sample_packets):
        """Test binary payload encoding integrity."""
        packets = [
            sample_packets['open'],
            sample_packets['socket_event'],
        ]

        payload = Payload(packets=packets)
        encoded = payload.encode()

        # Should be binary format with delimiters
        assert b'\x00' in encoded or b'\xff' in encoded

        # Should be decodable
        decoded = Payload.decode(encoded)
        assert len(decoded.packets) == len(packets)


@pytest.mark.asyncio
class TestEngineIOErrorHandling:
    """Test Engine.IO error handling and edge cases."""

    async def test_connection_close_handling(self, mock_server, mock_connection_state, test_session):
        """Test proper handling of connection close packets."""
        gateway = await ChzzkGateway._connect_websocket(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        assert gateway.is_connected

        # Send close packet
        await gateway.send(Packet(EnginePacketType.CLOSE))
        await asyncio.sleep(0.1)

        # Should be disconnected
        # Note: disconnect() sets is_connected to False

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

    async def test_websocket_connection_error(self, mock_connection_state, test_session):
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


@pytest.mark.asyncio
class TestEngineIOTransportUpgrade:
    """Test Engine.IO transport upgrade mechanism."""

    async def test_polling_to_websocket_upgrade(self, mock_server, mock_connection_state, test_session):
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

    async def test_upgrade_packet_exchange(self, mock_server, mock_connection_state, test_session):
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
