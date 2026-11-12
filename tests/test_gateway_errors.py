"""MIT License

Copyright (c) 2024-2025 gunyu1019

Gateway error-path tests.
Tests how the gateway behaves when the handshake stalls, the polling transport is
used, frames are broken, or the heartbeat cannot be sent.
"""

import asyncio
import json
import time

import aiohttp
import pydantic
import pytest
import pytest_asyncio
from yarl import URL

import chzzkpy.gateway as gateway_module
from chzzkpy.enums import EnginePacketType, SocketPacketType
from chzzkpy.error import ChatConnectFailed, ReceiveErrorPacket
from chzzkpy.gateway import ChzzkGateway, OpenPacketInfo
from chzzkpy.packet import Packet
from chzzkpy.payload import Payload

from test_engine_io import (
    acquired_connections,
    guard_read_loop_spinning,
    track_websockets,
)

READ_TIMEOUT = 5.0


class Recorder:
    """An event hook that remembers what it was called with."""

    def __init__(self):
        self.calls = []

    async def __call__(self, data):
        self.calls.append(data)


def event_packet(name: str, data=None, packet_id=None) -> Packet:
    return Packet(
        EnginePacketType.MESSAGE,
        SocketPacketType.EVENT,
        data=[name] if data is None else [name, data],
        packet_id=packet_id,
    )


class ShortTimeoutAsyncio:
    """asyncio as the gateway module sees it, with its 5 second handshake timeout cut.

    Only the timeout of the handshake is shortened: the ping timeout stays as it is.
    """

    handshake_timeout = 5.0

    def __init__(self, timeout: float):
        self.timeout = timeout

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def wait_for(self, awaitable, timeout=None):
        if timeout == self.handshake_timeout:
            timeout = self.timeout
        return await asyncio.wait_for(awaitable, timeout=timeout)


@pytest.fixture
def short_handshake_timeout(monkeypatch):
    monkeypatch.setattr(gateway_module, "asyncio", ShortTimeoutAsyncio(0.2))


def upgrade_open_packet(mock_server) -> OpenPacketInfo:
    return OpenPacketInfo(
        sid=mock_server.sid,
        upgrades=["websocket"],
        ping_interval=int(mock_server.ping_interval),
        ping_timeout=int(mock_server.ping_timeout),
    )


class GatewayConnector:
    """Open gateways of the mock server, and close them when the test ends."""

    def __init__(self, mock_server, session):
        self.mock_server = mock_server
        self.session = session
        self.gateways: list[ChzzkGateway] = []

    async def websocket(self, event_hook=None) -> ChzzkGateway:
        gateway = await ChzzkGateway._connect_websocket(
            url=self.mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=self.session,
            event_hook=event_hook,
            ssl=False,
        )
        self.gateways.append(gateway)
        return gateway

    async def polling(self, event_hook=None, hold=True) -> ChzzkGateway:
        """Open a gateway on the polling transport, the way a server without
        websocket upgrade offers it. The server answers a poll once it has a packet.
        """
        self.mock_server.upgrades = []
        self.mock_server._poll_hold = hold
        gateway = await ChzzkGateway._connect_polling(
            url=self.mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=self.session,
            event_hook=event_hook,
            ssl=False,
        )
        self.gateways.append(gateway)
        assert gateway.current_transport == "polling"
        return gateway


@pytest_asyncio.fixture
async def connect(mock_server, test_session):
    connector = GatewayConnector(mock_server, test_session)
    yield connector
    for gateway in connector.gateways:
        await gateway._close()


async def assert_ended_quietly(task: asyncio.Task):
    """The task ended, by being cancelled or by returning, but without an error."""
    await asyncio.wait({task}, timeout=READ_TIMEOUT)
    assert task.done()
    assert task.cancelled() or task.exception() is None


async def assert_torn_down(gateway: ChzzkGateway):
    """The gateway is disconnected and its background tasks have ended cleanly."""
    assert not gateway.is_connected
    await asyncio.wait({gateway._ping_loop_task}, timeout=READ_TIMEOUT)
    assert gateway._ping_loop_task.done()
    if not gateway._ping_loop_task.cancelled():
        assert gateway._ping_loop_task.exception() is None
    if gateway.websocket is not None:
        assert gateway.websocket.closed


@pytest.mark.asyncio
class TestWebSocketHandshakeTimeouts:
    """Test a handshake the server never answers gives up and cleans up."""

    async def test_unanswered_upgrade_probe_fails_upgrade(
        self, mock_server, test_session, monkeypatch, short_handshake_timeout
    ):
        """Test the upgrade fails, and the websocket is closed, without a PONG."""
        websockets = track_websockets(monkeypatch)
        mock_server._withhold_probe_reply = True

        with pytest.raises(ChatConnectFailed) as error:
            await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                open_packet=upgrade_open_packet(mock_server),
                ssl=False,
            )

        assert str(error.value) == str(ChatConnectFailed.websocket_upgrade_failed())
        assert len(websockets) == 1
        assert websockets[0].closed

    async def test_unanswered_upgrade_probe_falls_back_to_polling(
        self, mock_server, test_session, monkeypatch, short_handshake_timeout
    ):
        """Test a connection whose upgrade stalls goes on with the polling transport."""
        websockets = track_websockets(monkeypatch)
        mock_server._withhold_probe_reply = True
        opened = Recorder()

        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            event_hook={EnginePacketType.OPEN: opened},
            ssl=False,
        )

        assert gateway.current_transport == "polling"
        assert gateway.is_connected
        assert gateway.session_id == mock_server.sid
        assert gateway.websocket is None
        assert [websocket.closed for websocket in websockets] == [True]
        # The packets of the handshake are delivered once, by the polling gateway
        assert [call["sid"] for call in opened.calls] == [mock_server.sid]

        await gateway.disconnect()

    async def test_missing_open_packet_fails_connect(
        self, mock_server, test_session, monkeypatch, short_handshake_timeout
    ):
        """Test a direct connection fails, and closes, without an OPEN packet."""
        websockets = track_websockets(monkeypatch)
        mock_server._withhold_open = True

        with pytest.raises(ChatConnectFailed) as error:
            await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                ssl=False,
            )

        assert str(error.value) == str(ChatConnectFailed.websocket_connect_failed())
        assert len(websockets) == 1
        assert websockets[0].closed

    @pytest.mark.parametrize("upgrade", [True, False], ids=["probe", "open_packet"])
    async def test_cancelled_handshake_closes_websocket(
        self, mock_server, test_session, monkeypatch, upgrade, wait_until
    ):
        """Test the websocket is closed when the waiting connect is cancelled."""
        websockets = track_websockets(monkeypatch)
        mock_server._withhold_probe_reply = True
        mock_server._withhold_open = True

        connect_task = asyncio.ensure_future(
            ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                open_packet=upgrade_open_packet(mock_server) if upgrade else None,
                ssl=False,
            )
        )
        # The websocket is only seen once connect is inside its handshake
        await wait_until(lambda: websockets, message="the websocket to be opened")
        assert not connect_task.done()

        connect_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await connect_task

        assert len(websockets) == 1
        assert websockets[0].closed


@pytest.mark.asyncio
class TestPollingTransport:
    """Test the packets received over the polling transport reach the hooks."""

    async def test_polling_session(
        self, mock_server, connect, wait_until, wait_finished
    ):
        """Test events, pings, acks and CLOSE over a whole polling session."""
        mock_server.ping_interval = 100
        mock_server.ping_timeout = 10000
        events, closes = Recorder(), Recorder()
        gateway = await connect.polling(
            event_hook={
                SocketPacketType.EVENT: events,
                EnginePacketType.CLOSE: closes,
            }
        )
        assert gateway.base_url.query["sid"] == mock_server.sid
        read_task = gateway.read_in_background()

        # An event polled from the server reaches its hook
        mock_server.queue_polling_packet(event_packet("chat", {"nick": "viewer"}))
        await wait_until(lambda: events.calls, message="the polled event")
        assert events.calls == [["chat", {"nick": "viewer"}]]

        # The next PING is only sent once the previous one was answered by a polled
        # PONG, otherwise the heartbeat times out and closes the connection.
        await wait_until(
            lambda: mock_server.received_messages.count("2") >= 3,
            message="the heartbeat to go on",
        )
        assert gateway.is_connected

        # An event with a packet id is acknowledged through a POST
        mock_server.queue_polling_packet(event_packet("chat", {"nick": "ack"}, 0))
        await wait_until(
            lambda: b"\x00\x03\xff430" in mock_server.post_bodies,
            message="the ACK to be posted",
        )
        assert events.calls[-1] == ["chat", {"nick": "ack"}]

        # The server closes the session: the gateway says goodbye and stops reading
        mock_server.queue_polling_packet(Packet(EnginePacketType.CLOSE))
        await wait_finished(read_task)
        assert len(closes.calls) == 1
        await assert_torn_down(gateway)
        assert acquired_connections(connect.session) == 0
        # DISCONNECT, then CLOSE: the goodbye of the client
        await wait_until(
            lambda: "1" in mock_server.received_messages, message="the goodbye"
        )
        messages = mock_server.received_messages
        assert messages.index("41") < messages.index("1")

    async def test_packets_of_one_response_arrive_in_order(
        self, mock_server, connect, wait_until
    ):
        """Test several packets in a single polling response are all delivered."""
        events = Recorder()
        gateway = await connect.polling(event_hook={SocketPacketType.EVENT: events})
        read_task = gateway.read_in_background()

        for number in range(3):
            mock_server.queue_polling_packet(event_packet("chat", {"number": number}))
        await wait_until(lambda: len(events.calls) == 3, message="3 events")

        assert events.calls == [["chat", {"number": number}] for number in range(3)]
        assert gateway.is_connected
        assert not read_task.done()

    async def test_noop_responses_are_ignored(self, mock_server, connect, wait_until):
        """Test the read loop goes on polling after a response of only a NOOP."""
        events = Recorder()
        mock_server._poll_raw_bodies = [
            Payload([Packet(EnginePacketType.NOOP)]).encode()
        ]
        gateway = await connect.polling(event_hook={SocketPacketType.EVENT: events})
        read_task = gateway.read_in_background()

        mock_server.queue_polling_packet(event_packet("chat", "after noop"))
        await wait_until(lambda: events.calls, message="the event after the NOOP")

        assert events.calls == [["chat", "after noop"]]
        assert mock_server._poll_raw_bodies == []
        assert not read_task.done()

    async def test_invalid_packet_ends_read_task(
        self, mock_server, connect, wait_finished
    ):
        """Test a polled packet that can't be decoded closes the connection."""
        gateway = await connect.polling()
        mock_server._poll_raw_bodies = [b"\x00\x01\xffx"]
        read_task = gateway.read_in_background()

        with pytest.raises(ValueError):
            await wait_finished(read_task)

        await assert_torn_down(gateway)

    async def test_error_status_ends_read_task(
        self, mock_server, connect, wait_finished
    ):
        """Test a failing poll closes the connection, whatever the error status."""
        gateway = await connect.polling()
        mock_server._poll_error_status = 503
        read_task = gateway.read_in_background()

        with pytest.raises(ReceiveErrorPacket) as error:
            await wait_finished(read_task)

        assert error.value.current_transport == "polling"
        assert error.value.data == 503
        await assert_torn_down(gateway)

    async def test_handshake_without_open_packet_is_rejected(
        self, mock_server, test_session
    ):
        """Test a handshake response whose first packet isn't OPEN can't connect."""
        mock_server._handshake_body = Payload([Packet(EnginePacketType.NOOP)]).encode()

        with pytest.raises(pydantic.ValidationError):
            await ChzzkGateway._connect_polling(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                ssl=False,
            )

        assert acquired_connections(test_session) == 0

    async def test_send_payload_posts_all_packets_at_once(
        self, mock_server, connect, wait_until
    ):
        """Test a Payload given to send() is a single POST with all its packets."""
        gateway = await connect.polling()
        await wait_until(lambda: mock_server.post_bodies, message="the first ping")
        mock_server.post_bodies.clear()
        mock_server.received_messages.clear()

        payload = Payload([event_packet("first"), event_packet("second", {"n": 2})])
        await gateway.send(payload)

        assert mock_server.post_bodies == [payload.encode()]
        assert mock_server.received_messages == ['42["first"]', '42["second",{"n":2}]']

    async def test_send_payload_sends_websocket_frame_per_packet(
        self, mock_server, connect, wait_until
    ):
        """Test a Payload given to send() is one frame per packet over a websocket."""
        gateway = await connect.websocket()
        await wait_until(lambda: mock_server.received_messages, message="the ping")
        mock_server.received_messages.clear()

        await gateway.send(
            Payload([event_packet("first"), event_packet("second", {"n": 2})])
        )

        await wait_until(
            lambda: len(mock_server.received_messages) >= 2, message="both frames"
        )
        assert mock_server.received_messages == ['42["first"]', '42["second",{"n":2}]']


@pytest.mark.asyncio
class TestWebSocketReceive:
    """Test what the websocket read loop does with frames it can't use."""

    async def test_protocol_error_frame_ends_read_task(
        self, mock_server, connect, wait_finished
    ):
        """Test a broken websocket frame closes the gateway with ReceiveErrorPacket."""
        gateway = await connect.websocket()
        guard_read_loop_spinning(gateway)
        read_task = gateway.read_in_background()

        # A frame with a reserved opcode: aiohttp reports it as an ERROR message
        mock_server.send_raw_frame(b"\x83\x00")

        with pytest.raises(ReceiveErrorPacket) as error:
            await wait_finished(read_task)

        assert error.value.current_transport == "websocket"
        assert isinstance(error.value.data, aiohttp.http.WebSocketError)
        assert error.value.data.code == aiohttp.WSCloseCode.PROTOCOL_ERROR
        await assert_torn_down(gateway)

    @pytest.mark.parametrize(
        "frame",
        [b"\x00\x01", "9", "47", "6"],
        ids=["binary_frame", "unknown_engine_type", "unknown_socket_type", "noop"],
    )
    async def test_unusable_frames_are_ignored(
        self, mock_server, connect, wait_until, frame
    ):
        """Test frames the gateway has no use for don't stop it from reading on."""
        events = Recorder()
        gateway = await connect.websocket(event_hook={SocketPacketType.EVENT: events})
        guard_read_loop_spinning(gateway)
        read_task = gateway.read_in_background()

        if isinstance(frame, bytes):
            await mock_server.send_binary(frame)
        else:
            await mock_server.send_text(frame)
        await mock_server.send_custom_packet(event_packet("chat", "still reading"))
        await wait_until(lambda: events.calls, message="the event after the frame")

        assert events.calls == [["chat", "still reading"]]
        assert gateway.is_connected
        assert not read_task.done()

    @pytest.mark.parametrize(
        ("frame", "error"),
        [
            ("", IndexError),
            ("x", ValueError),
            ("4", ValueError),
            ("42[bad", json.JSONDecodeError),
        ],
        ids=["empty", "not_a_packet", "missing_socket_type", "invalid_json"],
    )
    async def test_undecodable_frame_ends_read_task(
        self,
        mock_server,
        connect,
        frame,
        error,
        wait_finished,
    ):
        """Test a frame that isn't a packet fails the read task and closes the gateway."""
        gateway = await connect.websocket()
        guard_read_loop_spinning(gateway)
        read_task = gateway.read_in_background()

        await mock_server.send_text(frame)

        with pytest.raises(error):
            await wait_finished(read_task)

        await assert_torn_down(gateway)


@pytest.mark.asyncio
class TestHeartbeatFailures:
    """Test a heartbeat that can't be sent closes the connection."""

    @pytest.mark.parametrize("status", [400, 500])
    async def test_failed_ping_post_closes_connection(
        self,
        mock_server,
        connect,
        status,
        wait_finished,
    ):
        """Test a rejected PING over polling ends the ping loop and the connection."""
        mock_server._post_status = status
        gateway = await connect.polling()
        read_task = gateway.read_in_background()

        # The first PING is sent as soon as the gateway starts.
        # The ping loop closes the connection instead of raising in its own task.
        assert await wait_finished(gateway._ping_loop_task) is None
        await assert_ended_quietly(read_task)

        await assert_torn_down(gateway)
        assert acquired_connections(connect.session) == 0

    @pytest.mark.parametrize(
        "error",
        [
            aiohttp.ClientConnectionResetError("Cannot write to closing transport"),
            ConnectionResetError("Connection lost"),
            aiohttp.ClientConnectionError("Connection lost"),
        ],
        ids=["client_reset", "reset", "client_error"],
    )
    async def test_failed_ping_send_closes_websocket(
        self,
        mock_server,
        connect,
        monkeypatch,
        error,
        wait_finished,
    ):
        """Test a PING that can't be written to the websocket closes the connection."""
        gateway = await connect.websocket()
        guard_read_loop_spinning(gateway)
        read_task = gateway.read_in_background()

        async def failing_send_str(*args, **kwargs):
            raise error

        # The ping loop hasn't had a chance to run yet: this fails its first PING.
        monkeypatch.setattr(gateway.websocket, "send_str", failing_send_str)

        assert await wait_finished(gateway._ping_loop_task) is None
        await assert_ended_quietly(read_task)

        await assert_torn_down(gateway)
        assert mock_server.received_messages == []

    async def test_ping_loop_stops_when_disconnected(
        self,
        mock_server,
        connect,
        wait_until,
        wait_finished,
    ):
        """Test the ping loop ends by itself, uncancelled, once not connected."""
        mock_server.ping_interval = 50
        gateway = await connect.websocket()
        gateway.read_in_background()
        await wait_until(
            lambda: mock_server.received_messages.count("2") >= 2,
            message="the heartbeat to be running",
        )

        # Not through _close(), so nothing cancels the ping loop
        gateway.is_connected = False

        assert await wait_finished(gateway._ping_loop_task) is None
        assert not gateway._ping_loop_task.cancelled()
        await gateway.websocket.close()


@pytest.mark.asyncio
class TestAcknowledgements:
    """Test the ACK sent for the received events that carry a packet id."""

    async def test_event_with_id_is_acknowledged_over_websocket(
        self, mock_server, connect, wait_until
    ):
        """Test an event with a packet id is delivered and acknowledged."""
        events = Recorder()
        gateway = await connect.websocket(event_hook={SocketPacketType.EVENT: events})
        gateway.read_in_background()

        # 0 is a packet id too, which a plain truthiness check would miss
        await mock_server.send_custom_packet(event_packet("chat", {"n": 1}, 0))

        await wait_until(lambda: "430" in mock_server.received_messages, message="ACK")
        await wait_until(lambda: events.calls, message="the event")
        assert events.calls == [["chat", {"n": 1}]]
        assert mock_server.received_messages.count("430") == 1

    async def test_event_with_id_is_acknowledged_over_polling(
        self, mock_server, connect, wait_until
    ):
        """Test the ACK of a polled event is posted, and the event is delivered."""
        events = Recorder()
        gateway = await connect.polling(event_hook={SocketPacketType.EVENT: events})
        gateway.read_in_background()

        mock_server.queue_polling_packet(event_packet("chat", {"n": 1}, 0))

        ack_body = b"\x00\x03\xff430"
        await wait_until(lambda: ack_body in mock_server.post_bodies, message="ACK")
        await wait_until(lambda: events.calls, message="the event")
        assert events.calls == [["chat", {"n": 1}]]

    @pytest.mark.parametrize("packet_id", [0, 7, 42, 456])
    async def test_ack_carries_the_id_of_the_event(
        self, mock_server, connect, wait_until, packet_id
    ):
        """Test the ACK answers the packet id of the event it acknowledges."""
        events = Recorder()
        gateway = await connect.websocket(event_hook={SocketPacketType.EVENT: events})

        # Handed over as decoded, so this holds whatever the decoding does to the id
        await gateway.received_message(event_packet("chat", {"n": 1}, packet_id))

        expected = f"43{packet_id}"
        await wait_until(
            lambda: expected in mock_server.received_messages, message="the ACK"
        )
        assert [m for m in mock_server.received_messages if m.startswith("43")] == [
            expected
        ]
        assert events.calls == [["chat", {"n": 1}]]

    @pytest.mark.parametrize(
        "packet",
        [
            event_packet("chat", {"n": 1}),
            Packet(EnginePacketType.MESSAGE, SocketPacketType.ACK, packet_id=0),
            Packet(
                EnginePacketType.MESSAGE,
                SocketPacketType.CONNECT_ERROR,
                data={"message": "denied"},
                packet_id=0,
            ),
        ],
        ids=["event_without_id", "ack_with_id", "connect_error_with_id"],
    )
    async def test_other_packets_are_not_acknowledged(
        self, mock_server, connect, wait_until, packet
    ):
        """Test only an EVENT that has a packet id gets an ACK."""
        hook = Recorder()
        gateway = await connect.websocket(
            event_hook={
                packet.socket_packet_type: hook,
                SocketPacketType.DISCONNECT: hook,
            }
        )
        gateway.read_in_background()

        await mock_server.send_custom_packet(packet)
        await mock_server.send_custom_packet(
            Packet(EnginePacketType.MESSAGE, SocketPacketType.DISCONNECT)
        )
        await wait_until(lambda: len(hook.calls) == 2, message="both packets")
        # Frames arrive in order, so an ACK would be ahead of this one
        await gateway.send_ping("sentinel")
        await wait_until(
            lambda: "2sentinel" in mock_server.received_messages,
            message="the sentinel",
        )

        assert not [
            message
            for message in mock_server.received_messages
            if message.startswith("43")
        ]

    async def test_send_ack_over_websocket(self, mock_server, connect, wait_until):
        """Test the ACK frame holds the packet id and nothing else."""
        gateway = await connect.websocket()

        await gateway.send_ack(7)

        await wait_until(
            lambda: "437" in mock_server.received_messages, message="the ACK frame"
        )
        assert mock_server.received_messages.count("437") == 1

    async def test_send_ack_over_polling(self, mock_server, connect):
        """Test the ACK is posted as a payload of a single packet."""
        gateway = await connect.polling()
        mock_server.post_bodies.clear()

        await gateway.send_ack(7)

        assert mock_server.post_bodies == [b"\x00\x03\xff437"]


@pytest.mark.asyncio
class TestHooks:
    """Test hooks can be changed while the gateway is running."""

    async def test_unset_hooks_default_to_none(self, mock_server, connect):
        """Test a gateway has an entry for every packet type, empty unless given."""
        hook = Recorder()
        gateway = await connect.websocket(event_hook={SocketPacketType.EVENT: hook})

        assert set(gateway._event_hook) == set(SocketPacketType) | set(EnginePacketType)
        assert gateway._event_hook[SocketPacketType.EVENT] is hook
        assert [
            packet_type
            for packet_type, func in gateway._event_hook.items()
            if func is not None
        ] == [SocketPacketType.EVENT]

    async def test_set_hook_and_remove_hook(self, mock_server, connect, wait_until):
        """Test set_hook() replaces a hook and remove_hook() stops its calls."""
        first, second, barrier = Recorder(), Recorder(), Recorder()
        gateway = await connect.websocket(
            event_hook={
                SocketPacketType.EVENT: first,
                SocketPacketType.CONNECT_ERROR: barrier,
            }
        )
        gateway.read_in_background()

        await mock_server.send_custom_packet(event_packet("chat", "one"))
        await wait_until(lambda: first.calls, message="the first hook")

        gateway.set_hook(SocketPacketType.EVENT, second)
        assert gateway._event_hook[SocketPacketType.EVENT] is second
        await mock_server.send_custom_packet(event_packet("chat", "two"))
        await wait_until(lambda: second.calls, message="the replacing hook")

        gateway.remove_hook(SocketPacketType.EVENT)
        assert gateway._event_hook[SocketPacketType.EVENT] is None
        await mock_server.send_custom_packet(event_packet("chat", "three"))
        # Packets are handled in order: once this one is seen, "three" has been dropped
        await mock_server.send_custom_packet(
            Packet(
                EnginePacketType.MESSAGE,
                SocketPacketType.CONNECT_ERROR,
                data={"message": "barrier"},
            )
        )
        await wait_until(lambda: barrier.calls, message="the barrier packet")

        assert first.calls == [["chat", "one"]]
        assert second.calls == [["chat", "two"]]
        assert gateway.is_connected

    async def test_set_hook_for_engine_packet(
        self, mock_server, connect, wait_until, wait_finished
    ):
        """Test hooks of engine packets can be set after connecting too."""
        closes = Recorder()
        gateway = await connect.websocket()
        guard_read_loop_spinning(gateway)
        read_task = gateway.read_in_background()

        gateway.set_hook(EnginePacketType.CLOSE, closes)
        await mock_server.send_custom_packet(Packet(EnginePacketType.CLOSE))

        await wait_finished(read_task)
        assert len(closes.calls) == 1
        await assert_torn_down(gateway)


class TestUrlHelpers:
    """Test the URLs the gateway builds for the Engine.IO endpoints."""

    @pytest.mark.parametrize("as_url", [False, True], ids=["str", "URL"])
    @pytest.mark.parametrize(
        ("transport", "ssl", "expected"),
        [
            (
                "polling",
                True,
                "https://example.com:8080/socket.io/?token=abc&EIO=3&transport=polling",
            ),
            (
                "polling",
                False,
                "http://example.com:8080/socket.io/?token=abc&EIO=3&transport=polling",
            ),
            (
                "websocket",
                True,
                "wss://example.com:8080/socket.io/?token=abc&EIO=3&transport=websocket",
            ),
            (
                "websocket",
                False,
                "ws://example.com:8080/socket.io/?token=abc&EIO=3&transport=websocket",
            ),
        ],
    )
    def test_engineio_url(self, as_url, transport, ssl, expected):
        """Test the scheme follows the transport and ssl, and the query is kept."""
        url = "http://example.com:8080/api/session?token=abc"

        engine_url = ChzzkGateway._get_engineio_url(
            URL(url) if as_url else url, "socket.io", transport, ssl=ssl
        )

        assert str(engine_url) == expected

    def test_engineio_url_keeps_given_url_unchanged(self):
        """Test building the Engine.IO URL doesn't change the URL it is given."""
        url = URL("http://example.com/api?token=abc")

        ChzzkGateway._get_engineio_url(url, "socket.io", "polling")

        assert str(url) == "http://example.com/api?token=abc"

    def test_engineio_url_custom_engine_path(self):
        """Test the engine path replaces the path of the URL."""
        engine_url = ChzzkGateway._get_engineio_url(
            "https://ssc.example.com/ignored", "/custom/io", "polling"
        )

        assert (
            str(engine_url)
            == "https://ssc.example.com/custom/io/?EIO=3&transport=polling"
        )

    def test_timestamp_url(self, monkeypatch):
        """Test a timestamp is added to the URL, once."""
        monkeypatch.setattr(time, "time", lambda: 1700000000.5)
        url = URL("https://example.com/socket.io/?EIO=3")

        stamped = ChzzkGateway._get_timestamp_url(url)

        assert stamped.query["t"] == "1700000000.5"
        assert stamped.query["EIO"] == "3"
        assert ChzzkGateway._get_timestamp_url(stamped) == stamped

    def test_timestamp_url_keeps_existing_timestamp(self):
        """Test a URL that has a timestamp is returned as it is."""
        url = URL("https://example.com/socket.io/?t=1&EIO=3")

        assert ChzzkGateway._get_timestamp_url(url) is url


@pytest.mark.asyncio
class TestStateIntegration:
    """Test what the connection state does with the events it can't use."""

    async def test_unknown_event_and_system_type_are_ignored(
        self, mock_server, mock_connection_state, connect, wait_until
    ):
        """Test unknown events don't dispatch anything, or break the connection."""
        state = mock_connection_state
        state.debug_mode = False
        dispatched = []
        state.dispatch = lambda event, *args, **kwargs: dispatched.append(event)
        hooks = {
            packet_type: func
            for packet_type, func in state.gateway_parsers.items()
            if func is not None
        }
        barrier = Recorder()
        hooks[SocketPacketType.CONNECT_ERROR] = barrier
        gateway = await connect.websocket(event_hook=hooks)
        read_task = gateway.read_in_background()

        await mock_server.send_custom_packet(event_packet("nothing-like-this", {}))
        await mock_server.send_custom_packet(
            event_packet(
                "SYSTEM", json.dumps({"type": "not-a-system-type", "data": {}})
            )
        )
        await mock_server.send_custom_packet(
            Packet(EnginePacketType.MESSAGE, SocketPacketType.CONNECT_ERROR, data={})
        )
        await wait_until(lambda: barrier.calls, message="the barrier packet")

        assert dispatched == []
        assert gateway.is_connected
        assert not read_task.done()


@pytest.mark.asyncio
class TestKnownBugs:
    """Tests of the correct behavior that the implementation doesn't have yet.

    Each one fails today and is marked as an expected failure. Once the matching bug
    is fixed the test passes, which strict mode reports: remove the marker then.
    """

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="Packet._decode_socket counts the first digit of the packet id twice",
    )
    @pytest.mark.parametrize("packet_id", [1, 7, 12, 456])
    async def test_packet_id_survives_decoding(self, packet_id):
        encoded = event_packet("chat", {"n": 1}, packet_id).encode()
        assert encoded == f'42{packet_id}["chat",{{"n":1}}]'

        assert Packet.decode(encoded).id == packet_id

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="the packet id of a received event is decoded wrong, so is its ACK",
    )
    async def test_received_event_is_acknowledged_with_its_own_id(
        self, mock_server, connect, wait_until
    ):
        gateway = await connect.websocket()
        gateway.read_in_background()

        await mock_server.send_custom_packet(event_packet("chat", {"n": 1}, 7))

        await wait_until(
            lambda: any(m.startswith("43") for m in mock_server.received_messages),
            message="the ACK",
        )
        assert [m for m in mock_server.received_messages if m.startswith("43")] == [
            "437"
        ]

    @pytest.mark.xfail(
        strict=True,
        raises=ValueError,
        reason="Payload.decode advances past a text packet without its length prefix",
    )
    async def test_text_payload_is_decoded(self):
        payload = Payload.decode(b"1:22:40")

        assert [packet.encode() for packet in payload.packets] == ["2", "40"]

    @pytest.mark.xfail(
        strict=True,
        raises=AttributeError,
        reason="Payload.decode returns None, not a Payload, for an empty body",
    )
    async def test_empty_payload_has_no_packets(self):
        payload = Payload.decode(b"")

        assert payload.packets == []

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="an empty polling response kills the read loop with an AttributeError",
    )
    async def test_empty_poll_response_does_not_end_the_connection(
        self, mock_server, connect, wait_until
    ):
        events = Recorder()
        mock_server._poll_raw_bodies = [b""]
        gateway = await connect.polling(event_hook={SocketPacketType.EVENT: events})
        read_task = gateway.read_in_background()

        mock_server.queue_polling_packet(event_packet("chat", "after empty"))
        await wait_until(
            lambda: events.calls or read_task.done(), message="the next poll"
        )

        failure = read_task.exception() if read_task.done() else None
        assert failure is None, repr(failure)
        assert events.calls == [["chat", "after empty"]]

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="Payload.encode takes the length in characters, not in bytes",
    )
    async def test_payload_length_counts_bytes(self):
        packet = Packet(EnginePacketType.PING, data="안녕")

        encoded = Payload([packet]).encode()

        assert encoded == b"\x00\x07\xff" + "2안녕".encode("utf-8")
        assert Payload.decode(encoded).packets[0].data == "안녕"

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="a websocket closed during the upgrade probe raises TypeError",
    )
    async def test_server_close_during_probe_fails_upgrade(
        self, mock_server, test_session
    ):
        mock_server._close_before_reply = True

        with pytest.raises(Exception) as error:
            await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                open_packet=upgrade_open_packet(mock_server),
                ssl=False,
            )

        assert isinstance(error.value, ChatConnectFailed), repr(error.value)

    @pytest.mark.xfail(
        strict=True,
        raises=TypeError,
        reason="a websocket closed during the upgrade probe skips the polling fallback",
    )
    async def test_server_close_during_probe_falls_back_to_polling(
        self, mock_server, test_session
    ):
        mock_server._close_before_reply = True

        gateway = await ChzzkGateway._connect_polling(
            url=mock_server.url,
            engine_path="socket.io",
            loop=asyncio.get_running_loop(),
            session=test_session,
            ssl=False,
        )

        assert gateway.current_transport == "polling"
        assert gateway.is_connected
        await gateway.disconnect()

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="a websocket closed before the OPEN packet raises TypeError",
    )
    async def test_server_close_before_open_packet_fails_connect(
        self, mock_server, test_session
    ):
        mock_server._close_before_reply = True

        with pytest.raises(Exception) as error:
            await ChzzkGateway._connect_websocket(
                url=mock_server.url,
                engine_path="socket.io",
                loop=asyncio.get_running_loop(),
                session=test_session,
                ssl=False,
            )

        assert isinstance(error.value, ChatConnectFailed), repr(error.value)
