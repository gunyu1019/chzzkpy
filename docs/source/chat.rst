Chat Feature
============

Client
------

.. autoclass:: chzzkpy.chat.ChatClient
   :members:
   :show-inheritance:
   :exclude-members: event

Event Refenence
---------------

This section describes the events listened that :class:`ChatClient<chzzkpy.chat.ChatClient>` received.
You can received event with decorator `event` method.

For example:

.. code-block:: python

   >>> @client.event
   ... async def on_chat(message: ChatMessage):
   ...     print(message.content)

All event method must be a coroutine. Otherwise, unexpected errors may occur.

.. py:function:: on_chat(message: ChatMessage)
   :async:

   Call when a :class:`ChatMesage<chzzkpy.chat.ChatMessage>` is created and sent.
   
   :param ChatMessage message: The current message.

.. py:function:: on_connect()
   :async:

   Called when the client has successfully connected to chzzk chat.

.. py:function:: on_donation(donation: DonationMessage)
   :async:

   Called when a broadcaster received donation.
   Donation types include Chat, Video, and Mission, which are all invoked.

   :param DonationMessage message: The message included donation info.

.. py:function:: on_system_message(system_message: SystemMessage)
   :async:

   Called when a :class:`SystemMessage<chzzkpy.chat.SystemMessage>` is created and sent.

   :param SystemMessage message: The system message.

.. py:function:: on_subscription(subscription: SubscriptionMessage)
   :async:

   Called when a broadcast participant registered a new subscription.

   :param SubscriptionMessage message: The message included subscription info.

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

Enumerations
------------

.. autoclass:: chzzkpy.chat.UserRole()
   :members:
   :undoc-members:

Blind
-----
This model is used in the `on_blind` event handler, which contains the blinded message.

.. autoclass:: chzzkpy.chat.Blind()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

Connection
----------

.. autoclass:: chzzkpy.chat.ConnectedInfo()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

Donation
--------

.. autoclass:: chzzkpy.chat.DonationRank()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

.. autoclass:: chzzkpy.chat.BaseDonation()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

.. autoclass:: chzzkpy.chat.ChatDonation()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.VideoDonation()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.MissionDonation()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

Message
-------
.. autoclass:: chzzkpy.chat.Message()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

.. autoclass:: chzzkpy.chat.MessageDetail()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.ChatMessage()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.NoticeMessage()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.DonationMessage()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.SubscriptionMessage()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.SystemMessage()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

Message Extra
-------------
.. autoclass:: chzzkpy.chat.Extra()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

.. autoclass:: chzzkpy.chat.NoticeExtra()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.ChatDonationExtra()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.VideoDonationExtra()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.MissionDonationExtra()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:
   :no-index:

.. autoclass:: chzzkpy.chat.SubscriptionExtra()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.SystemExtra()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.SystemExtraParameter()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

Profile
-------
.. autoclass:: chzzkpy.chat.Profile()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

.. autoclass:: chzzkpy.chat.Badge()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

.. autoclass:: chzzkpy.chat.ActivityBadge()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.chat.StreamingProperty()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:

Recent Chat
-----------
This model is used in the `on_recent_chat` event handler, which contains the historical messages.

.. autoclass:: chzzkpy.chat.RecentChat()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields
   :undoc-members:


Exceptions
----------
The `Chat Features` exceptions section describes exceptions that can be thrown by `ChatClient`. 
Exceptions that occur in the `Basic Features` exceptions section can also occur.


.. autoexception:: chzzkpy.chat.ChatConnectFailed()

.. autoexception:: chzzkpy.chat.ConnectionClosed()

.. autoexception:: chzzkpy.chat.WebSocketClosure()

.. autoexception:: chzzkpy.chat.ReconnectWebsocket()