from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

import engineio
import pytest
import pytest_asyncio
import socketio
from aiohttp import web

from chzzkpy.authorization import AccessToken


class FakeHTTPResponse:
    def __init__(
        self,
        status: int = 200,
        reason: str = "OK",
        payload: dict[str, Any] | None = None,
        body: bytes = b"",
    ):
        self.status = status
        self.reason = reason
        self._payload = payload or {}
        self._body = body

    async def json(self) -> dict[str, Any]:
        return self._payload

    async def read(self) -> bytes:
        return self._body


@dataclass
class LocalEngineIOServer:
    app: web.Application
    runner: web.AppRunner
    site: web.TCPSite
    eio: engineio.AsyncServer
    base_url: str
    connected: asyncio.Event = field(default_factory=asyncio.Event)
    disconnected: asyncio.Event = field(default_factory=asyncio.Event)
    messages: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    connected_sids: set[str] = field(default_factory=set)


@dataclass
class LocalSocketIOServer:
    app: web.Application
    runner: web.AppRunner
    site: web.TCPSite
    sio: socketio.AsyncServer
    base_url: str
    connected: asyncio.Event = field(default_factory=asyncio.Event)
    disconnected: asyncio.Event = field(default_factory=asyncio.Event)
    auth_payloads: asyncio.Queue[dict[str, Any] | None] = field(
        default_factory=asyncio.Queue
    )
    client_events: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    connected_sids: set[str] = field(default_factory=set)


@pytest.fixture
def access_token() -> AccessToken:
    return AccessToken(
        accessToken="test-access",
        refreshToken="test-refresh",
        token_type="Bearer",
        expiresIn=3600,
    )


@pytest_asyncio.fixture
async def engineio_server() -> LocalEngineIOServer:
    eio = engineio.AsyncServer(
        async_mode="aiohttp",
        ping_interval=1,
        ping_timeout=2,
        allow_upgrades=True,
        cors_allowed_origins="*",
        logger=False,
    )
    app = web.Application()
    eio.attach(app, engineio_path="engine.io")

    connected = asyncio.Event()
    disconnected = asyncio.Event()
    messages: asyncio.Queue[Any] = asyncio.Queue()
    connected_sids: set[str] = set()

    @eio.on("connect")
    async def on_connect(sid, _environ):
        connected_sids.add(sid)
        connected.set()

    @eio.on("disconnect")
    async def on_disconnect(sid):
        connected_sids.discard(sid)
        disconnected.set()

    @eio.on("message")
    async def on_message(sid, data):
        await messages.put(data)
        await eio.send(sid, data)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()

    host, port = runner.addresses[0][0], runner.addresses[0][1]
    base_url = f"http://{host}:{port}"

    server = LocalEngineIOServer(
        app=app,
        runner=runner,
        site=site,
        eio=eio,
        base_url=base_url,
        connected=connected,
        disconnected=disconnected,
        messages=messages,
        connected_sids=connected_sids,
    )

    try:
        yield server
    finally:
        for sid in list(connected_sids):
            with contextlib.suppress(Exception):
                await eio.disconnect(sid)

        with contextlib.suppress(Exception):
            await site.stop()
        with contextlib.suppress(Exception):
            await runner.cleanup()

        await asyncio.sleep(0)
        current = asyncio.current_task()
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not current
            and not task.done()
            and any(token in repr(task.get_coro()) for token in ("engineio", "aiohttp"))
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


@pytest_asyncio.fixture
async def socketio_server() -> LocalSocketIOServer:
    sio = socketio.AsyncServer(
        async_mode="aiohttp",
        cors_allowed_origins="*",
        logger=False,
        engineio_logger=False,
        allow_upgrades=True,
    )
    app = web.Application()
    sio.attach(app, socketio_path="socket.io")

    connected = asyncio.Event()
    disconnected = asyncio.Event()
    auth_payloads: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    client_events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    connected_sids: set[str] = set()

    @sio.event(namespace="/chat")
    async def connect(sid, environ, auth):
        connected_sids.add(sid)
        connected.set()
        await auth_payloads.put(auth)

    @sio.event(namespace="/chat")
    async def disconnect(sid):
        connected_sids.discard(sid)
        disconnected.set()

    @sio.event(namespace="/chat")
    async def client_ping(sid, data):
        await client_events.put({"sid": sid, "data": data})
        await sio.emit("server_pong", {"echo": data}, to=sid, namespace="/chat")
        return {"ok": True}

    @sio.event(namespace="/chat")
    async def join_room(sid, room_name):
        await sio.enter_room(sid, room_name, namespace="/chat")

    @sio.event(namespace="/chat")
    async def broadcast_room(_sid, data):
        room_name = data["room"]
        payload = data["payload"]
        await sio.emit("room_message", payload, room=room_name, namespace="/chat")

    @sio.event(namespace="/chat")
    async def force_disconnect(sid):
        await sio.disconnect(sid, namespace="/chat")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()

    host, port = runner.addresses[0][0], runner.addresses[0][1]
    base_url = f"http://{host}:{port}"

    server = LocalSocketIOServer(
        app=app,
        runner=runner,
        site=site,
        sio=sio,
        base_url=base_url,
        connected=connected,
        disconnected=disconnected,
        auth_payloads=auth_payloads,
        client_events=client_events,
        connected_sids=connected_sids,
    )

    try:
        yield server
    finally:
        for sid in list(connected_sids):
            with contextlib.suppress(Exception):
                await sio.disconnect(sid, namespace="/chat")

        with contextlib.suppress(Exception):
            await site.stop()
        with contextlib.suppress(Exception):
            await runner.cleanup()

        await asyncio.sleep(0)
        current = asyncio.current_task()
        pending = [
            task
            for task in asyncio.all_tasks()
            if task is not current
            and not task.done()
            and any(
                token in repr(task.get_coro())
                for token in ("engineio", "socketio", "aiohttp")
            )
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
