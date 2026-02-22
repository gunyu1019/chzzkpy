from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
import socketio


@pytest.mark.asyncio
async def test_socketio_namespace_connect_and_auth_payload(socketio_server):
	client = socketio.AsyncClient(logger=False, engineio_logger=False)

	connected = asyncio.Event()

	@client.event(namespace="/chat")
	async def connect():
		connected.set()

	auth_data = {"token": "test-token", "scope": ["chat:read"]}

	await client.connect(
		socketio_server.base_url,
		socketio_path="socket.io",
		namespaces=["/chat"],
		auth=auth_data,
		transports=["websocket"],
	)

	await asyncio.wait_for(connected.wait(), timeout=3)
	received_auth = await asyncio.wait_for(socketio_server.auth_payloads.get(), timeout=3)

	assert received_auth == auth_data

	await client.disconnect()


@pytest.mark.asyncio
async def test_socketio_custom_event_emit_and_receive(socketio_server):
	client = socketio.AsyncClient(logger=False, engineio_logger=False)

	received_payload: list[dict] = []

	@client.on("server_pong", namespace="/chat")
	async def on_server_pong(data):
		received_payload.append(data)

	await client.connect(
		socketio_server.base_url,
		socketio_path="socket.io",
		namespaces=["/chat"],
		auth={"token": "abc"},
		transports=["websocket"],
	)

	await client.emit("client_ping", {"value": 99}, namespace="/chat")
	server_received = await asyncio.wait_for(socketio_server.client_events.get(), timeout=3)

	for _ in range(15):
		if received_payload:
			break
		await asyncio.sleep(0.1)

	assert server_received["data"] == {"value": 99}
	assert received_payload == [{"echo": {"value": 99}}]

	await client.disconnect()


@pytest.mark.asyncio
async def test_socketio_room_broadcast_to_multiple_clients(socketio_server):
	client_a = socketio.AsyncClient(logger=False, engineio_logger=False)
	client_b = socketio.AsyncClient(logger=False, engineio_logger=False)

	room_messages_a: list[dict] = []
	room_messages_b: list[dict] = []

	@client_a.on("room_message", namespace="/chat")
	async def on_room_message_a(data):
		room_messages_a.append(data)

	@client_b.on("room_message", namespace="/chat")
	async def on_room_message_b(data):
		room_messages_b.append(data)

	await client_a.connect(
		socketio_server.base_url,
		socketio_path="socket.io",
		namespaces=["/chat"],
		auth={"token": "a"},
		transports=["websocket"],
	)
	await client_b.connect(
		socketio_server.base_url,
		socketio_path="socket.io",
		namespaces=["/chat"],
		auth={"token": "b"},
		transports=["websocket"],
	)

	room_name = "alpha-room"
	await client_a.emit("join_room", room_name, namespace="/chat")
	await client_b.emit("join_room", room_name, namespace="/chat")

	await asyncio.sleep(0.2)

	payload = {"message": "hello-room"}
	await client_a.emit(
		"broadcast_room",
		{"room": room_name, "payload": payload},
		namespace="/chat",
	)

	for _ in range(20):
		if room_messages_a and room_messages_b:
			break
		await asyncio.sleep(0.1)

	assert room_messages_a[-1] == payload
	assert room_messages_b[-1] == payload

	await client_a.disconnect()
	await client_b.disconnect()


@pytest.mark.asyncio
async def test_socketio_reconnection_with_backoff_after_unexpected_disconnect(socketio_server):
	reconnect_delay = 0.1
	client = socketio.AsyncClient(
		logger=False,
		engineio_logger=False,
		reconnection=True,
		reconnection_attempts=3,
		reconnection_delay=reconnect_delay,
		reconnection_delay_max=0.3,
		randomization_factor=0,
	)

	connected_count = 0
	disconnected = asyncio.Event()

	@client.event(namespace="/chat")
	async def connect():
		nonlocal connected_count
		connected_count += 1

	@client.event(namespace="/chat")
	async def disconnect():
		disconnected.set()

	await client.connect(
		socketio_server.base_url,
		socketio_path="socket.io",
		namespaces=["/chat"],
		auth={"token": "reconnect"},
		transports=["websocket"],
	)

	assert connected_count == 1

	client.eio.state = "connected"
	await client._handle_eio_disconnect("transport error")
	await asyncio.wait_for(disconnected.wait(), timeout=3)
	assert client._reconnect_task is not None

	client._reconnect_task.cancel()
	await asyncio.gather(client._reconnect_task, return_exceptions=True)

	delays: list[float] = []

	async def fake_wait_for(_awaitable, timeout):
		if hasattr(_awaitable, "close"):
			_awaitable.close()
		delays.append(timeout)
		raise asyncio.TimeoutError

	connect_attempts = {"count": 0}

	async def fake_connect(*args, **kwargs):
		connect_attempts["count"] += 1
		if connect_attempts["count"] < 3:
			raise socketio.exceptions.ConnectionError("temporary down")
		return None

	client._reconnect_abort = asyncio.Event()
	client.connection_url = socketio_server.base_url
	client.connection_headers = {}
	client.connection_auth = {"token": "reconnect"}
	client.connection_transports = ["websocket"]
	client.connection_namespaces = ["/chat"]
	client.socketio_path = "socket.io"
	client.connect = AsyncMock(side_effect=fake_connect)

	import socketio.async_client as async_client_module

	original_wait_for = async_client_module.asyncio.wait_for
	async_client_module.asyncio.wait_for = fake_wait_for
	try:
		await client._handle_reconnect()
	finally:
		async_client_module.asyncio.wait_for = original_wait_for

	assert client.connect.await_count == 3
	assert delays[:3] == [0.1, 0.2, 0.3]
	assert connect_attempts["count"] == 3

	await client.eio.disconnect(abort=True)
