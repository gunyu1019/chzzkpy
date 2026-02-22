from __future__ import annotations

import asyncio

import engineio
import pytest


@pytest.mark.asyncio
async def test_engineio_handshake_and_connect(engineio_server):
	client = engineio.AsyncClient(logger=False)

	await client.connect(
		engineio_server.base_url,
		engineio_path="engine.io",
		transports=["polling", "websocket"],
	)

	await asyncio.wait_for(engineio_server.connected.wait(), timeout=3)
	assert client.sid is not None

	await client.disconnect()
	await asyncio.wait_for(engineio_server.disconnected.wait(), timeout=3)


@pytest.mark.asyncio
async def test_engineio_ping_pong_heartbeat_keeps_connection_alive(engineio_server):
	client = engineio.AsyncClient(logger=False)

	await client.connect(
		engineio_server.base_url,
		engineio_path="engine.io",
		transports=["polling", "websocket"],
	)

	await asyncio.wait_for(engineio_server.connected.wait(), timeout=3)
	await asyncio.sleep(2.2)

	received: list[str] = []

	@client.on("message")
	async def on_message(data):
		if isinstance(data, str):
			received.append(data)

	await client.send("heartbeat-ok")
	server_data = await asyncio.wait_for(engineio_server.messages.get(), timeout=3)

	for _ in range(10):
		if received:
			break
		await asyncio.sleep(0.1)

	assert server_data == "heartbeat-ok"
	assert received == ["heartbeat-ok"]

	await client.disconnect()


@pytest.mark.asyncio
async def test_engineio_upgrade_from_polling_to_websocket(engineio_server):
	client = engineio.AsyncClient(logger=False)

	await client.connect(
		engineio_server.base_url,
		engineio_path="engine.io",
		transports=["polling", "websocket"],
	)

	await asyncio.wait_for(engineio_server.connected.wait(), timeout=3)

	for _ in range(20):
		if client.transport() == "websocket":
			break
		await asyncio.sleep(0.1)

	assert client.transport() == "websocket"

	await client.disconnect()


@pytest.mark.asyncio
async def test_engineio_raw_text_and_binary_integrity(engineio_server):
	client = engineio.AsyncClient(logger=False)

	received_text: list[str] = []
	received_binary: list[bytes] = []

	@client.on("message")
	async def on_message(data):
		if isinstance(data, bytes):
			received_binary.append(data)
		elif isinstance(data, str):
			received_text.append(data)

	await client.connect(
		engineio_server.base_url,
		engineio_path="engine.io",
		transports=["websocket"],
	)

	text_payload = "plain-text-packet"
	binary_payload = b"\x00\x01raw-binary\xff"

	await client.send(text_payload)
	server_text = await asyncio.wait_for(engineio_server.messages.get(), timeout=3)

	await client.send(binary_payload)
	server_binary = await asyncio.wait_for(engineio_server.messages.get(), timeout=3)

	for _ in range(15):
		if len(received_text) >= 1 and len(received_binary) >= 1:
			break
		await asyncio.sleep(0.1)

	assert server_text == text_payload
	assert server_binary == binary_payload
	assert received_text[-1] == text_payload
	assert received_binary[-1] == binary_payload

	await client.disconnect()
