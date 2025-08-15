Receive and send message
========================
The “채팅 메시지 조회” and ”채팅 메시지 쓰기” API Scopes are required.

.. code-block:: python

    from chzzkpy import Client, Donation, Message, UserPermission

    client_id = "Application Client ID"
    client_secret = "Application Client Secret"
    client = Client(client_id, client_secret)

    @client.event
    async def on_chat(message: Message):
        if message.content == "!안녕":
            await message.send("%s님, 안녕하세요!" % message.profile.nickname)


    async def main():
        user_client = await client.login()
        await user_client.connect(UserPermission.all())

    asyncio.run(main())

To receive and send messages, UserClient authentication is required.
Use the :class:`UserClient.connect <chzzkpy.client.UserClient.connect>` method to wait for messages from the user channel.
The `connect` method parameter subscribes to message receiving permissions through :class:`UserPermission <chzzkpy.flags.UserPermission>`.

The message can be received through the `on_chat` event.
The :class:`Message <chzzkpy.message.Message>` instance contains channel, and the :class:`send() <chzzkpy.message.Message.send>` method is used to reply to the receiving channel.