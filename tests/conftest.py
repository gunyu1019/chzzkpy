"""MIT License

Copyright (c) 2024-2025 gunyu1019

Test fixtures and mock server for engine.io and socket.io protocol testing.
"""

import asyncio
import pytest
import pytest_asyncio
import json
import ssl
from aiohttp import web
import aiohttp
from typing import Optional, List, Dict, Any
from urllib.parse import parse_qs

# Import chzzkpy internal implementations
from chzzkpy.packet import Packet
from chzzkpy.payload import Payload
from chzzkpy.enums import EnginePacketType, SocketPacketType


def create_test_session():
    """Create an aiohttp session suitable for testing (no SSL verification)."""
    connector = aiohttp.TCPConnector(ssl=False)
    return aiohttp.ClientSession(connector=connector)


class MockEngineIOServer:
    """Mock Engine.IO server for testing protocol compliance."""

    def __init__(self):
        self.sid = "test-session-id-12345"
        self.ping_interval = 25000  # 25 seconds
        self.ping_timeout = 60000   # 60 seconds
        self.upgrades = ["websocket"]
        self.connections: Dict[str, web.WebSocketResponse] = {}
        self.received_messages: List[str] = []
        self.emit_events: List[tuple[str, Any]] = []
        self._auto_pong = True
        self._accept_upgrade = True

    def _create_open_packet(self) -> Packet:
        """Create engine.io OPEN packet."""
        open_data = {
            "sid": self.sid,
            "upgrades": self.upgrades,
            "pingInterval": self.ping_interval,
            "pingTimeout": self.ping_timeout,
        }
        return Packet(EnginePacketType.OPEN, data=open_data)

    def _create_socket_connect_packet(self) -> Packet:
        """Create socket.io CONNECT packet."""
        return Packet(EnginePacketType.MESSAGE, SocketPacketType.CONNECT)

    async def handle_polling(self, request: web.Request) -> web.Response:
        """Handle engine.io polling transport."""
        sid = request.query.get('sid')

        if request.method == 'GET':
            if sid is None:
                # Initial handshake
                payload = Payload(packets=[
                    self._create_open_packet(),
                    self._create_socket_connect_packet(),
                ])
                return web.Response(
                    body=payload.encode(),
                    content_type='application/octet-stream',
                )
            else:
                # Polling for messages
                # Return empty or pending messages
                payload = Payload(packets=[Packet(EnginePacketType.NOOP)])
                return web.Response(
                    body=payload.encode(),
                    content_type='application/octet-stream',
                )

        elif request.method == 'POST':
            # Client sending data via polling
            body = await request.read()
            payload = Payload.decode(body)
            for packet in payload.packets:
                self.received_messages.append(packet.encode())
            return web.Response(text='ok')

        return web.Response(status=400)

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle engine.io websocket transport."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        sid = request.query.get('sid')

        if sid is None:
            # Direct websocket connection (no upgrade)
            open_packet = self._create_open_packet()
            await ws.send_str(open_packet.encode())

            # Send socket.io CONNECT
            connect_packet = self._create_socket_connect_packet()
            await ws.send_str(connect_packet.encode())

            self.connections[self.sid] = ws
        else:
            # Websocket upgrade from polling
            self.connections[sid] = ws

            # Handle upgrade handshake (ping/pong probe + upgrade packet)
            upgrade_complete = False
            try:
                # Loop to handle ping probe and upgrade packet
                for _ in range(2):  # Expect 2 messages: PING probe and UPGRADE
                    msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                    if msg.type != web.WSMsgType.TEXT:
                        break

                    packet = Packet.decode(msg.data)

                    if packet.engine_packet_type == EnginePacketType.PING and packet.data == "probe":
                        # Send pong probe
                        pong_packet = Packet(EnginePacketType.PONG, data="probe")
                        await ws.send_str(pong_packet.encode())

                        if not self._accept_upgrade:
                            await ws.close()
                            return ws

                    elif packet.engine_packet_type == EnginePacketType.UPGRADE:
                        # Upgrade successful
                        upgrade_complete = True
                        break

            except asyncio.TimeoutError:
                # Timeout waiting for upgrade, close connection
                await ws.close()
                return ws

        # Main message loop
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                packet = Packet.decode(msg.data)
                self.received_messages.append(msg.data)

                if packet.engine_packet_type == EnginePacketType.PING:
                    if self._auto_pong:
                        pong_packet = Packet(EnginePacketType.PONG)
                        await ws.send_str(pong_packet.encode())

                elif packet.engine_packet_type == EnginePacketType.MESSAGE:
                    if packet.socket_packet_type == SocketPacketType.EVENT:
                        # Handle socket.io event
                        event_name = packet.data[0] if isinstance(packet.data, list) else "unknown"
                        self.emit_events.append((event_name, packet.data))

                        # Send ACK if packet has ID
                        if packet.id is not None:
                            ack_packet = Packet(
                                EnginePacketType.MESSAGE,
                                SocketPacketType.ACK,
                                packet_id=packet.id,
                            )
                            await ws.send_str(ack_packet.encode())

                    elif packet.socket_packet_type == SocketPacketType.DISCONNECT:
                        close_packet = Packet(EnginePacketType.CLOSE)
                        await ws.send_str(close_packet.encode())
                        await ws.close()
                        return ws

                elif packet.engine_packet_type == EnginePacketType.CLOSE:
                    await ws.close()
                    return ws

            elif msg.type == web.WSMsgType.ERROR:
                break

        return ws

    async def broadcast_event(self, event_name: str, data: Any):
        """Broadcast socket.io event to all connected clients."""
        event_packet = Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=[event_name, data],
        )

        for ws in self.connections.values():
            if not ws.closed:
                await ws.send_str(event_packet.encode())

    async def send_custom_packet(self, packet: Packet, sid: Optional[str] = None):
        """Send custom packet to specific or all clients."""
        target_sid = sid or self.sid
        ws = self.connections.get(target_sid)
        if ws and not ws.closed:
            await ws.send_str(packet.encode())


@pytest_asyncio.fixture
async def mock_server():
    """Create and start a mock engine.io/socket.io server."""
    app = web.Application()
    server_instance = MockEngineIOServer()

    # Combined handler that routes to polling or websocket based on transport parameter
    async def combined_handler(request: web.Request):
        transport = request.query.get('transport', 'polling')
        if transport == 'websocket':
            return await server_instance.handle_websocket(request)
        else:
            return await server_instance.handle_polling(request)

    # Setup routes
    app.router.add_get('/socket.io/', combined_handler)
    app.router.add_post('/socket.io/', server_instance.handle_polling)

    # Start server
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, 'localhost', 0)  # Random available port
    await site.start()

    port = site._server.sockets[0].getsockname()[1]
    server_url = f"http://localhost:{port}"

    # Attach server instance and URL for tests
    server_instance.url = server_url
    server_instance.runner = runner

    yield server_instance

    # Cleanup
    await runner.cleanup()


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def mock_connection_state():
    """Create a mock ConnectionState for testing."""
    from chzzkpy.state import ConnectionState

    dispatched_events = []

    def mock_dispatch(event: str, *args, **kwargs):
        dispatched_events.append((event, args, kwargs))

    state = ConnectionState(
        dispatch=mock_dispatch,
        handler={},
        http=None,  # Not needed for pure protocol tests
        debug_mode=True,
    )
    state.dispatched_events = dispatched_events

    return state


@pytest.fixture
def sample_packets():
    """Provide sample packets for testing."""
    return {
        'open': Packet(
            EnginePacketType.OPEN,
            data={
                'sid': 'test-sid',
                'upgrades': ['websocket'],
                'pingInterval': 25000,
                'pingTimeout': 60000,
            }
        ),
        'ping': Packet(EnginePacketType.PING),
        'pong': Packet(EnginePacketType.PONG),
        'ping_probe': Packet(EnginePacketType.PING, data='probe'),
        'pong_probe': Packet(EnginePacketType.PONG, data='probe'),
        'upgrade': Packet(EnginePacketType.UPGRADE),
        'close': Packet(EnginePacketType.CLOSE),
        'socket_connect': Packet(EnginePacketType.MESSAGE, SocketPacketType.CONNECT),
        'socket_disconnect': Packet(EnginePacketType.MESSAGE, SocketPacketType.DISCONNECT),
        'socket_event': Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=['test_event', {'key': 'value'}],
        ),
        'socket_event_with_id': Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.EVENT,
            data=['test_event', {'key': 'value'}],
            packet_id=1,
        ),
        'socket_ack': Packet(
            EnginePacketType.MESSAGE,
            SocketPacketType.ACK,
            packet_id=1,
        ),
    }



@pytest_asyncio.fixture
async def test_session():
    """Create a test session with SSL disabled."""
    connector = aiohttp.TCPConnector(ssl=False)
    session = aiohttp.ClientSession(connector=connector)
    yield session
    await session.close()


