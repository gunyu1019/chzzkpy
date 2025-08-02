(Legacy) Chat API Reference
===========================

Client
------

.. autoclass:: chzzkpy.unofficial.chat.ChatClient
   :members:
   :member-order: groupwise
   :show-inheritance:
   :exclude-members: event

Event Refenence
---------------

This section describes the events listened that :class:`ChatClient<chzzkpy.unofficial.chat.ChatClient>` received.
You can received event with decorator `event` method.

For example:

.. code-block:: python

   >>> @client.event
   ... async def on_chat(message: ChatMessage):
   ...     print(message.content)

All event method must be a coroutine. Otherwise, unexpected errors may occur.

.. py:function:: on_chat(message: ChatMessage)
   :async:

   Call when a :class:`ChatMesage<chzzkpy.unofficial.chat.ChatMessage>` is created and sent.
   
   :param ChatMessage message: The current message.

.. py:function:: on_connect()
   :async:

   Called when the client has successfully connected to chzzk chat.

.. py:function:: on_donation(donation: DonationMessage)
   :async:

   Called when a broadcaster received donation.
   Donation types include Chat, Video, and Mission, which are all invoked.

   :param DonationMessage donation: The message included donation info.

.. py:function:: on_system_message(system_message: SystemMessage)
   :async:

   Called when a :class:`SystemMessage<chzzkpy.unofficial.chat.SystemMessage>` is created and sent.

   :param SystemMessage message: The system message.

.. py:function:: on_subscription(subscription: SubscriptionMessage)
   :async:

   Called when a broadcast participant registered a new subscription.

   :param SubscriptionMessage subscription: The message included subscription info.

.. py:function:: on_recent_chat(messages: RecentChat)
   :async:

   Called when a client requests a recent chat and receives a response.

   :param RecentChat messages: The historical messages


.. py:function:: on_pin(message: NoticeMessage)
   :async:

   Called when a broadcaster created a pin message.
   You can use `on_notice` event hanlder, instead of `on_pin` event handler.

   :param NoticeMessage message: The notice message that a broadcaster pinned.


.. py:function:: on_unpin(message: NoticeMessage)
   :async:

   Called when a broadcaster removed a pin message.

   :param NoticeMessage message: The notice message that a broadcaster un-pinned.


.. py:function:: on_blind(message: Blind)
   :async:

   Called when a broadcaster or manager blinded a chat.

   :param Blind message: The blinded message.

.. py:function:: on_mission_completed(mission: MissionDonation)
   :async:

   Called when a broadcaster completed a mission.

   :param MissionDonation mission: The mission donation that a broadcaster cleared.

.. py:function:: on_mission_pending(mission: MissionDonation)
   :async:

   Called when a broadcast participant created a new mission.

   :param MissionDonation mission: The mission donation that a broadcaster cleared.

.. py:function:: on_mission_approved(mission: MissionDonation)
   :async:

   Called when a broadcaster approved a mission.

   :param MissionDonation mission: The mission donation that a broadcaster approved.

.. py:function:: on_mission_rejected(mission: MissionDonation)
   :async:

   Called when a broadcaster rejected a mission.

   :param MissionDonation mission: The mission donation that a broadcaster rejected.

.. py:function:: on_client_error(exception: Exception, *args, **kwargs)
   :async:

   Called when an event hanlder raised exception.
   The `*args` and `**kwargs` argument includes event handler arguments.

Blind
-----
This model is used in the `on_blind` event handler, which contains the blinded message.

.. autoclass:: chzzkpy.unofficial.chat.Blind()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Connection
----------

.. autoclass:: chzzkpy.unofficial.chat.ConnectedInfo()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Donation
--------

.. autoclass:: chzzkpy.unofficial.chat.DonationRank()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.chat.BaseDonation()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.chat.ChatDonation()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.VideoDonation()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.MissionDonation()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

Message
-------
.. autoclass:: chzzkpy.unofficial.chat.Message()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init, model_validate_with_client
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.chat.MessageDetail()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.ChatMessage()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.NoticeMessage()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.DonationMessage()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.SubscriptionMessage()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.SystemMessage()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

Message Extra
-------------
.. autoclass:: chzzkpy.unofficial.chat.Extra()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.chat.NoticeExtra()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.ChatDonationExtra()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.VideoDonationExtra()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.MissionDonationExtra()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:
   :no-index:

.. autoclass:: chzzkpy.unofficial.chat.SubscriptionExtra()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.SystemExtra()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.SystemExtraParameter()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

Profile
-------
.. autoclass:: chzzkpy.unofficial.chat.Profile()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.chat.Badge()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.chat.ActivityBadge()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.chat.StreamingProperty()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Recent Chat
-----------
This model is used in the `on_recent_chat` event handler, which contains the historical messages.

.. autoclass:: chzzkpy.unofficial.chat.RecentChat()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:


Exceptions
----------
The `Chat Features` exceptions section describes exceptions that can be thrown by `ChatClient`. 
Exceptions that occur in the `Basic Features` exceptions section can also occur.


.. autoexception:: chzzkpy.unofficial.chat.ChatConnectFailed()

.. autoexception:: chzzkpy.unofficial.chat.ConnectionClosed()

.. autoexception:: chzzkpy.unofficial.chat.WebSocketClosure()

.. autoexception:: chzzkpy.unofficial.chat.ReconnectWebsocket()