(Official API) API Reference
============================


Client
------

.. autoclass:: chzzkpy.client.Client
   :members:
   :member-order: groupwise

User Client
-----------

.. autoclass:: chzzkpy.client.UserClient
   :members:
   :member-order: groupwise

Event Refenence
---------------

This section describes the events listened that :class:`ChatClient<chzzkpy.unofficial.chat.ChatClient>` received.
You can received event with decorator `event` method.

For example:

.. code-block:: python

   >>> @client.event
   ... async def on_chat(message: Message):
   ...     print(message.content)

All event method must be a coroutine. Otherwise, unexpected errors may occur.

.. py:function:: on_chat(message: message.Message)
   :async:

   Call when a :class:`ChatMesage<chzzkpy.message.Message>` is created and sent.
   
   :param Message message: The current message.

.. py:function:: on_connect()
   :async:

   Called when the client has successfully connected to chzzk chat.

.. py:function:: on_donation(donation: Donation)
   :async:

   Called when a broadcaster received donation.
   Donation types include Chat, and Video, which are all invoked.

   :param Donation donation: The message included donation info.

.. py:function:: on_subscription(subscription: Subscription)
   :async:

   Called when a broadcast participant registered a new subscription.

   :param Subscription subscription: The message included channel subscription info.

.. py:function:: on_permission_invoked(EventSubscribeMessage message)
   :async:

   Called when new permissions are granted by :class:`subscribe <chzzkpy.client.Client.subscribe>` method.

   :param EventSubscribeMessage message: The message included event subscription info.

.. py:function:: on_permission_reinvoked(EventSubscribeMessage message)
   :async:

   Called when permissions are retrieved by :class:`unsubscribe <chzzkpy.client.Client.unsubscribe>` method.

   :param EventSubscribeMessage message: The message included event subscription info.


.. py:function:: on_permission_reinvoked_force(EventSubscribeMessage message)
   :async:

   Called when permissions are revoked due to user consent withdrawal, etc.

   :param EventSubscribeMessage message: The message included event subscription info.


User Permission
---------------

.. autoclass:: chzzkpy.flags.UserPermission()
   :members:
   :member-order: groupwise
   :exclude-members: DEFAULT_VALUE, VALID_FLAGS
   :undoc-members:

Enumeration
-----------

.. autoclass:: chzzkpy.enums.FollowingPeriod()
   :members:
   :member-order: groupwise
   :undoc-members:

Authorization
-------------

.. autoclass:: chzzkpy.authorization.AccessToken()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Category
--------

.. autoclass:: chzzkpy.category.Category()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Channel
-------

.. autoclass:: chzzkpy.channel.Channel()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.channel.ChannelPermission()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.channel.FollowerInfo()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.channel.SubscriberInfo()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Chat
----

.. autoclass:: chzzkpy.chat.ChatSetting()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Live
----

.. autoclass:: chzzkpy.live.Live()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.live.BrodecastSetting()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Message
-------

.. autoclass:: chzzkpy.message.Profile()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.message.Message()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

   .. py:function:: send(content)
      :async:

      Send a message to the received channel

      :param str content: A content of message to send.
      :return: A instance containing the contents of the sent
      :rtype: SentMessage

.. autoclass:: chzzkpy.message.Donation()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

   .. py:function:: send(content)
      :async:

      Send a message to the received channel

      :param str content: A content of message to send.
      :return: A instance containing the contents of the sent
      :rtype: SentMessage

.. autoclass:: chzzkpy.message.Subscription()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

   .. py:function:: send(content)
      :async:

      Send a message to the received channel

      :param str content: A content of message to send.
      :return: A instance containing the contents of the sent
      :rtype: SentMessage

.. autoclass:: chzzkpy.message.SentMessage()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Restrict
--------

.. autoclass:: chzzkpy.restriction.RestrictUser()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Exceptions
----------

.. autoexception:: chzzkpy.error.LoginRequired()

.. autoexception:: chzzkpy.error.ChatConnectFailed()

.. autoexception:: chzzkpy.error.ReceiveErrorPacket()

.. autoexception:: chzzkpy.error.HTTPException()

.. autoexception:: chzzkpy.error.BadRequestException()

.. autoexception:: chzzkpy.error.UnauthorizedException()

.. autoexception:: chzzkpy.error.ForbiddenException()

.. autoexception:: chzzkpy.error.NotFoundException()

.. autoexception:: chzzkpy.error.TooManyRequestsException()