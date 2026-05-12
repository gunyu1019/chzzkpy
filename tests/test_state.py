"""MIT License

Unit tests for chzzkpy.state.ConnectionState class.

These tests verify the core dispatcher functionality including:
- Gateway and event parser registration via decorators
- Gateway packet routing and handling
- Event parsing and payload assembly
- Message object creation and state injection
"""

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from chzzkpy.state import ConnectionState
from chzzkpy.enums import EnginePacketType, SocketPacketType


class TestConnectionState:
    """Test suite for ConnectionState class"""

    @pytest.fixture
    def mock_dispatch(self):
        """Mock dispatch function"""
        return MagicMock()

    @pytest.fixture
    def mock_handler(self):
        """Mock handler dictionary"""
        return {"connect": AsyncMock(), "channel_id_invoked": AsyncMock()}

    @pytest.fixture
    def mock_http(self):
        """Mock HTTP session"""
        return MagicMock()

    @pytest.fixture
    def mock_access_token(self):
        """Mock access token"""
        return MagicMock()

    @pytest.fixture
    def connection_state(
        self, mock_dispatch, mock_handler, mock_http, mock_access_token
    ):
        """ConnectionState instance for testing"""
        return ConnectionState(
            dispatch=mock_dispatch,
            handler=mock_handler,
            http=mock_http,
            access_token=mock_access_token,
            debug_mode=True,
        )

    @pytest.fixture
    def connection_state_no_debug(self, mock_dispatch, mock_handler, mock_http):
        """ConnectionState instance without debug mode"""
        return ConnectionState(
            dispatch=mock_dispatch,
            handler=mock_handler,
            http=mock_http,
            debug_mode=False,
        )

    def test_initialization_parser_registration(self, connection_state):
        """Test that gateway and event parsers are properly registered during initialization"""
        # Verify gateway parsers are registered
        assert EnginePacketType.OPEN in connection_state.gateway_parsers

        # Verify the correct methods are registered for gateway parsing
        assert (
            connection_state.gateway_parsers[EnginePacketType.OPEN]
            == connection_state._handle_eio_connect
        )

        # The implementation uses socket_packet_type as key when both engine and socket types are specified
        gateway_parser_keys = list(connection_state.gateway_parsers.keys())

        # Should have OPEN, EVENT, CONNECT, and DISCONNECT type parsers
        assert EnginePacketType.OPEN in gateway_parser_keys
        assert SocketPacketType.EVENT in gateway_parser_keys
        assert SocketPacketType.CONNECT in gateway_parser_keys
        assert SocketPacketType.DISCONNECT in gateway_parser_keys

        # Verify the correct methods are mapped
        assert (
            connection_state.gateway_parsers[SocketPacketType.EVENT]
            == connection_state._handle_evnet
        )
        assert (
            connection_state.gateway_parsers[SocketPacketType.CONNECT]
            == connection_state._handle_connect
        )
        assert (
            connection_state.gateway_parsers[SocketPacketType.DISCONNECT]
            == connection_state._handle_disconnect
        )

        # Verify event parsers are registered
        assert "system" in connection_state.event_parsers
        assert "chat" in connection_state.event_parsers
        assert "donation" in connection_state.event_parsers
        assert "subscription" in connection_state.event_parsers

        # Verify the correct methods are registered for event parsing
        assert (
            connection_state.event_parsers["system"] == connection_state._handle_system
        )
        assert connection_state.event_parsers["chat"] == connection_state._handle_chat
        assert (
            connection_state.event_parsers["donation"]
            == connection_state._handle_donation
        )
        assert (
            connection_state.event_parsers["subscription"]
            == connection_state._handle_subscription
        )

    def test_initial_values(
        self,
        connection_state,
        mock_dispatch,
        mock_handler,
        mock_http,
        mock_access_token,
    ):
        """Test initial values are set correctly"""
        assert connection_state.dispatch == mock_dispatch
        assert connection_state.handler == mock_handler
        assert connection_state.http == mock_http
        assert connection_state.access_token == mock_access_token
        assert connection_state.debug_mode is True
        assert connection_state.gateway_id is None
        assert callable(connection_state.variable_access_token)
        assert callable(connection_state.json_serializer)

    def test_custom_json_serializer(self, mock_dispatch, mock_handler, mock_http):
        """Test custom JSON serializer is used"""
        custom_serializer = MagicMock(return_value={"test": "data"})
        state = ConnectionState(
            dispatch=mock_dispatch,
            handler=mock_handler,
            http=mock_http,
            json_serializer=custom_serializer,
        )
        assert state.json_serializer == custom_serializer

    def test_custom_variable_access_token(self, mock_dispatch, mock_handler, mock_http):
        """Test custom variable access token function is used"""
        custom_token_func = MagicMock()
        state = ConnectionState(
            dispatch=mock_dispatch,
            handler=mock_handler,
            http=mock_http,
            variable_access_token=custom_token_func,
        )
        assert state.variable_access_token == custom_token_func

    @pytest.mark.asyncio
    async def test_handle_eio_connect_debug_mode(self, connection_state):
        """Test Engine.IO connect handling in debug mode"""
        open_packet = {"sid": "test_session_id"}

        await connection_state._handle_eio_connect(open_packet)

        # Verify gateway_id is set
        assert connection_state.gateway_id == "test_session_id"

        # Verify dispatch is called in debug mode
        connection_state.dispatch.assert_called_once_with(
            "engine_connect", "test_session_id"
        )

    @pytest.mark.asyncio
    async def test_handle_eio_connect_no_debug(self, connection_state_no_debug):
        """Test Engine.IO connect handling without debug mode"""
        open_packet = {"sid": "test_session_id"}

        await connection_state_no_debug._handle_eio_connect(open_packet)

        # Verify gateway_id is set
        assert connection_state_no_debug.gateway_id == "test_session_id"

        # Verify dispatch is NOT called without debug mode
        connection_state_no_debug.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_connect_debug_mode(self, connection_state):
        """Test Socket.IO connect handling in debug mode"""
        await connection_state._handle_connect(None)

        # Verify dispatch is called in debug mode
        connection_state.dispatch.assert_called_once_with("socket_connect")

    @pytest.mark.asyncio
    async def test_handle_connect_no_debug(self, connection_state_no_debug):
        """Test Socket.IO connect handling without debug mode"""
        await connection_state_no_debug._handle_connect(None)

        # Verify dispatch is NOT called without debug mode
        connection_state_no_debug.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_disconnect_debug_mode(self, connection_state):
        """Test Socket.IO disconnect handling in debug mode"""
        await connection_state._handle_disconnect(None)

        # Verify dispatch is called in debug mode
        connection_state.dispatch.assert_called_once_with("socket_disconnect")

    @pytest.mark.asyncio
    async def test_handle_disconnect_no_debug(self, connection_state_no_debug):
        """Test Socket.IO disconnect handling without debug mode"""
        await connection_state_no_debug._handle_disconnect(None)

        # Verify dispatch is NOT called without debug mode
        connection_state_no_debug.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_evnet_with_known_event(self, connection_state):
        """Test event handling with known event type (note: _handle_evnet typo is intentional)"""
        # Mock the event parser
        mock_event_parser = AsyncMock()
        connection_state.event_parsers["chat"] = mock_event_parser

        event_data = ["chat", {"test": "data"}]

        await connection_state._handle_evnet(event_data)

        # Verify event parser is called with correct arguments
        mock_event_parser.assert_called_once_with({"test": "data"})

        # Verify debug dispatch is called
        connection_state.dispatch.assert_called_once_with(
            "socket_event", "chat", *event_data
        )

    @pytest.mark.asyncio
    async def test_handle_evnet_with_unknown_event(self, connection_state):
        """Test event handling with unknown event type"""
        event_data = ["unknown_event", {"test": "data"}]

        await connection_state._handle_evnet(event_data)

        # Verify debug dispatch is called even for unknown events
        connection_state.dispatch.assert_called_once_with(
            "socket_event", "unknown_event", *event_data
        )

    @pytest.mark.asyncio
    async def test_handle_evnet_no_debug(self, connection_state_no_debug):
        """Test event handling without debug mode"""
        # Use an unknown event to avoid triggering event handlers that try to parse JSON
        event_data = ["unknown_event", {"test": "data"}]

        await connection_state_no_debug._handle_evnet(event_data)

        # Verify dispatch is NOT called without debug mode
        connection_state_no_debug.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_handler_async(self, connection_state):
        """Test call_handler with async function"""
        await connection_state.call_handler("connect", "test_session")

        # Verify async handler is called
        connection_state.handler["connect"].assert_called_once_with("test_session")

    @pytest.mark.asyncio
    async def test_call_handler_sync(self, connection_state):
        """Test call_handler with sync function"""
        sync_handler = MagicMock()
        connection_state.handler["sync_test"] = sync_handler

        await connection_state.call_handler(
            "sync_test", "test_arg", test_kwarg="test_value"
        )

        # Verify sync handler is called
        sync_handler.assert_called_once_with("test_arg", test_kwarg="test_value")

    @pytest.mark.asyncio
    async def test_call_handler_nonexistent(self, connection_state):
        """Test call_handler with non-existent handler"""
        await connection_state.call_handler("nonexistent_handler", "test_arg")

        # Should not raise exception and should not call any handler
        # No assertions needed as we're testing it doesn't fail

    @pytest.mark.asyncio
    async def test_handle_system_connected(self, connection_state):
        """Test system event handling for 'connected' type"""
        raw_data = json.dumps(
            {"type": "connected", "data": {"sessionKey": "test_session_key"}}
        )

        await connection_state._handle_system(raw_data)

        # Verify dispatch and handler are called correctly
        connection_state.dispatch.assert_called_once_with("connect", "test_session_key")
        connection_state.handler["connect"].assert_called_once_with("test_session_key")

    @pytest.mark.asyncio
    @patch("chzzkpy.session.EventSubscribeMessage.model_validate")
    async def test_handle_system_subscribed(
        self, mock_model_validate, connection_state
    ):
        """Test system event handling for 'subscribed' type"""
        mock_event_message = MagicMock()
        mock_event_message.channel_id = "test_channel_123"
        mock_model_validate.return_value = mock_event_message

        raw_data = json.dumps(
            {
                "type": "subscribed",
                "data": {"eventType": "CHAT", "channelId": "test_channel_123"},
            }
        )

        await connection_state._handle_system(raw_data)

        # Verify EventSubscribeMessage.model_validate is called
        mock_model_validate.assert_called_once_with(
            {"eventType": "CHAT", "channelId": "test_channel_123"}
        )

        # Verify dispatch and handler are called correctly
        connection_state.dispatch.assert_called_once_with(
            "permission_invoked", mock_event_message
        )
        connection_state.handler["channel_id_invoked"].assert_called_once_with(
            "test_channel_123"
        )

    @pytest.mark.asyncio
    @patch("chzzkpy.session.EventSubscribeMessage.model_validate")
    async def test_handle_system_unsubscribed(
        self, mock_model_validate, connection_state
    ):
        """Test system event handling for 'unsubscribed' type"""
        mock_event_message = MagicMock()
        mock_event_message.channel_id = "test_channel_456"
        mock_model_validate.return_value = mock_event_message

        raw_data = json.dumps(
            {
                "type": "unsubscribed",
                "data": {"eventType": "DONATION", "channelId": "test_channel_456"},
            }
        )

        await connection_state._handle_system(raw_data)

        # Verify EventSubscribeMessage.model_validate is called
        mock_model_validate.assert_called_once_with(
            {"eventType": "DONATION", "channelId": "test_channel_456"}
        )

        # Verify dispatch and handler are called correctly
        connection_state.dispatch.assert_called_once_with(
            "permission_reinvoked", mock_event_message
        )
        connection_state.handler["channel_id_invoked"].assert_called_once_with(
            "test_channel_456"
        )

    @pytest.mark.asyncio
    @patch("chzzkpy.session.EventSubscribeMessage.model_validate")
    async def test_handle_system_revoked(self, mock_model_validate, connection_state):
        """Test system event handling for 'revoked' type"""
        mock_event_message = MagicMock()
        mock_event_message.channel_id = "test_channel_789"
        mock_model_validate.return_value = mock_event_message

        raw_data = json.dumps(
            {
                "type": "revoked",
                "data": {"eventType": "SUBSCRIPTION", "channelId": "test_channel_789"},
            }
        )

        await connection_state._handle_system(raw_data)

        # Verify EventSubscribeMessage.model_validate is called
        mock_model_validate.assert_called_once_with(
            {"eventType": "SUBSCRIPTION", "channelId": "test_channel_789"}
        )

        # Verify dispatch and handler are called correctly
        connection_state.dispatch.assert_called_once_with(
            "permission_reinvoked_force", mock_event_message
        )
        connection_state.handler["channel_id_invoked"].assert_called_once_with(
            "test_channel_789"
        )

    @pytest.mark.asyncio
    @patch("chzzkpy.message.Message.model_validate")
    async def test_handle_chat(self, mock_model_validate, connection_state):
        """Test chat event handling"""
        mock_message = MagicMock()
        mock_message.channel = "test_channel"
        mock_model_validate.return_value = mock_message

        raw_data = json.dumps(
            {
                "senderChannelId": "user123",
                "channelId": "test_channel",
                "content": "Hello world",
                "messageTime": 1234567890,
            }
        )

        await connection_state._handle_chat(raw_data)

        # Verify Message.model_validate is called
        mock_model_validate.assert_called_once_with(
            {
                "senderChannelId": "user123",
                "channelId": "test_channel",
                "content": "Hello world",
                "messageTime": 1234567890,
            }
        )

        # Verify message state and access token are set
        assert mock_message._state == connection_state
        assert mock_message._access_token == connection_state.access_token

        # Verify dispatch is called
        connection_state.dispatch.assert_called_once_with("chat", mock_message)

    @pytest.mark.asyncio
    @patch("chzzkpy.message.Message.model_validate")
    async def test_handle_chat_with_variable_access_token(
        self, mock_model_validate, mock_dispatch, mock_handler, mock_http
    ):
        """Test chat event handling with variable access token"""
        mock_variable_token_func = MagicMock(return_value="variable_token")
        connection_state = ConnectionState(
            dispatch=mock_dispatch,
            handler=mock_handler,
            http=mock_http,
            variable_access_token=mock_variable_token_func,
        )

        mock_message = MagicMock()
        mock_message.channel = "test_channel"
        mock_model_validate.return_value = mock_message

        raw_data = json.dumps({"channelId": "test_channel", "content": "Test"})

        await connection_state._handle_chat(raw_data)

        # Verify variable access token function is called
        mock_variable_token_func.assert_called_once_with("test_channel")

        # Verify message access token is set from variable function
        assert mock_message._access_token == "variable_token"

    @pytest.mark.asyncio
    @patch("chzzkpy.message.Donation.model_validate")
    async def test_handle_donation(self, mock_model_validate, connection_state):
        """Test donation event handling"""
        mock_donation = MagicMock()
        mock_donation.channel = "donation_channel"
        mock_model_validate.return_value = mock_donation

        raw_data = json.dumps(
            {
                "donationType": "CHAT",
                "channelId": "donation_channel",
                "donatorChannelId": "donator123",
                "donatorNickname": "Generous User",
                "payAmount": 1000,
                "donationText": "Keep up the good work!",
            }
        )

        await connection_state._handle_donation(raw_data)

        # Verify Donation.model_validate is called
        mock_model_validate.assert_called_once_with(
            {
                "donationType": "CHAT",
                "channelId": "donation_channel",
                "donatorChannelId": "donator123",
                "donatorNickname": "Generous User",
                "payAmount": 1000,
                "donationText": "Keep up the good work!",
            }
        )

        # Verify donation state and access token are set
        assert mock_donation._state == connection_state
        assert mock_donation._access_token == connection_state.access_token

        # Verify dispatch is called
        connection_state.dispatch.assert_called_once_with("donation", mock_donation)

    @pytest.mark.asyncio
    @patch("chzzkpy.message.Subscription.model_validate")
    async def test_handle_subscription(self, mock_model_validate, connection_state):
        """Test subscription event handling"""
        mock_subscription = MagicMock()
        mock_subscription.channel = "sub_channel"
        mock_model_validate.return_value = mock_subscription

        raw_data = json.dumps(
            {
                "channelId": "sub_channel",
                "subscriberChannelId": "subscriber123",
                "subscriberNickname": "New Subscriber",
                "tierNo": 1,
                "tierName": "Gold",
                "month": 3,
            }
        )

        await connection_state._handle_subscription(raw_data)

        # Verify Subscription.model_validate is called
        mock_model_validate.assert_called_once_with(
            {
                "channelId": "sub_channel",
                "subscriberChannelId": "subscriber123",
                "subscriberNickname": "New Subscriber",
                "tierNo": 1,
                "tierName": "Gold",
                "month": 3,
            }
        )

        # Verify subscription state and access token are set
        assert mock_subscription._state == connection_state
        assert mock_subscription._access_token == connection_state.access_token

        # Verify dispatch is called
        connection_state.dispatch.assert_called_once_with(
            "subscription", mock_subscription
        )

    @pytest.mark.asyncio
    async def test_handle_system_with_custom_json_serializer(
        self, mock_dispatch, mock_handler, mock_http
    ):
        """Test system event handling with custom JSON serializer"""
        custom_data = {"type": "connected", "data": {"sessionKey": "custom_session"}}
        custom_serializer = MagicMock(return_value=custom_data)

        connection_state = ConnectionState(
            dispatch=mock_dispatch,
            handler=mock_handler,
            http=mock_http,
            json_serializer=custom_serializer,
        )
        connection_state.handler = {"connect": AsyncMock()}

        raw_data = "custom_raw_data"

        await connection_state._handle_system(raw_data)

        # Verify custom serializer is called
        custom_serializer.assert_called_once_with(raw_data)

        # Verify the system event is processed correctly
        mock_dispatch.assert_called_once_with("connect", "custom_session")

    def test_dummy_method(self):
        """Test the dummy method returns its input unchanged"""
        test_payload = {"test": "data"}
        result = ConnectionState._ConnectionState__dummy_method(test_payload)
        assert result == test_payload

    def test_gateway_parsable_decorator(self):
        """Test gateway_parsable decorator functionality"""

        @ConnectionState.gateway_parsable(EnginePacketType.PING, SocketPacketType.ACK)
        def test_function():
            pass

        assert hasattr(test_function, "__gateway_parsing__")
        assert test_function.__gateway_parsing__ is True
        assert test_function.__parsing_engine_packet__ == EnginePacketType.PING
        assert test_function.__parsing_socket_packet__ == SocketPacketType.ACK

    def test_gateway_parsable_decorator_engine_only(self):
        """Test gateway_parsable decorator with engine packet type only"""

        @ConnectionState.gateway_parsable(EnginePacketType.OPEN)
        def test_function():
            pass

        assert hasattr(test_function, "__gateway_parsing__")
        assert test_function.__gateway_parsing__ is True
        assert test_function.__parsing_engine_packet__ == EnginePacketType.OPEN
        assert test_function.__parsing_socket_packet__ is None

    def test_event_parsable_decorator(self):
        """Test event_parsable decorator functionality"""

        @ConnectionState.event_parsable("test_event")
        def test_function():
            pass

        assert hasattr(test_function, "__event_parsing__")
        assert test_function.__event_parsing__ == "test_event"

    @pytest.mark.asyncio
    async def test_integration_complete_system_flow(self, connection_state):
        """Integration test for complete system event flow"""
        # Test the complete flow: gateway parsing -> event parsing -> handler calling

        # Mock event data that would come through gateway parsing
        system_event_data = [
            "system",
            json.dumps(
                {
                    "type": "connected",
                    "data": {"sessionKey": "integration_test_session"},
                }
            ),
        ]

        # Simulate the gateway parsing flow
        await connection_state._handle_evnet(system_event_data)

        # Verify both connect dispatch (from system parsing) and socket_event dispatch (from gateway parsing)
        assert connection_state.dispatch.call_count == 2

        # Check the calls
        calls = connection_state.dispatch.call_args_list

        # First call should be from _handle_system (connect event)
        first_call_args = calls[0][0]
        assert first_call_args[0] == "connect"
        assert first_call_args[1] == "integration_test_session"

        # Second call should be from _handle_evnet (debug mode)
        second_call_args = calls[1][0]
        assert second_call_args[0] == "socket_event"
        assert second_call_args[1] == "system"

        # Verify handler was called
        connection_state.handler["connect"].assert_called_once_with(
            "integration_test_session"
        )
