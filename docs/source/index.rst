Introduction
============
| 파이썬 기반의 치지직(네이버 라이브 스트리밍 서비스)의 비공식 라이브러리 입니다.
| An unofficial python library for Chzzk(Naver Live Streaming Service.

**Feature**

* Chatting in live.
* Search broadcaster, live, video.
* Lookup a live of broadcaster.
* Manage broadcast.

Installation
------------

**Python 3.10 or higher is required.**

.. code-block:: bash

   # Linux/MacOS
   python3 -m pip install chzzkpy

   # Windows
   py -3 -m pip install chzzkpy

To install the development version.

.. code-block:: bash

   $ git clone https://github.com/gunyu1019/chzzkpy.git -b develop
   $ cd chzzkpy
   $ python3 -m pip install -U .

Quick Example
-------------
This section is a simple example used in chzzpkpy.
You can see more examples at `Example Repository <https://github.com/gunyu1019/chzzkpy/tree/main/examples>`__ .

Searching broadcaster
`````````````````````

.. code-block:: python
   
   import asyncio
   import chzzkpy.unofficial


   async def main():
      client = chzzkpy.unofficial.Client()
      result = await client.search_channel("건유1019")
      if len(result) == 0:
         print("검색 결과가 없습니다 :(")
         await client.close()
         return
      
      print(result[0].name)
      print(result[0].id)
      print(result[0].image)
      await client.close()

   asyncio.run(main())


Chat Bot
````````

.. code-block:: python

   from chzzkpy import Client, Donation, Message, UserPermission

   client_id = "Prepared Client ID"
   client_secret = "Prepared Client Secret"
   client = Client(client_id, client_secret)

   @client.event
   async def on_chat(message: Message):
      if message.content == "!안녕":
         await message.send("%s님, 안녕하세요!" % message.profile.nickname)


   @client.event
   async def on_donation(donation: Donation):
      await donation.send("%s님, %d원 후원 감사합니다." % (donation.profile.nickname, donation.pay_amount))


   async def main():
      user_client = await client.login()
      await user_client.connect(UserPermission.all())

   asyncio.run(main())


Chat Bot(Unofficial)
````````````````````

.. code-block:: python

   from chzzkpy.chat import ChatClient, ChatMessage, DonationMessage

   client = ChatClient("channel_id")


   @client.event
   async def on_chat(message: ChatMessage):
      if message.content == "!안녕":
         await client.send_chat("%s님, 안녕하세요!" % message.profile.nickname)


   @client.event
   async def on_donation(message: DonationMessage):
      await client.send_chat("%s님, %d원 후원 감사합니다." % (message.profile.nickname, message.extras.pay_amount))


   client.run("NID_AUT", "NID_SES")

Collect Followers
`````````````````

.. code-block:: python
   
   from chzzkpy import Client, Donation, Message, UserPermission

   client_id = "Prepared Client ID"
   client_secret = "Prepared Client Secret"
   client = Client(client_id, client_secret)


   async def main():
      user_client = await client.login()
      result = await user_client.get_followers()
      if len(result) == 0:
         print("팔로워가 없습니다. :(")
         await client.close()
         return

      for user in result.data:
         print(f"{user.user_name}: {user.created_date}부터 팔로우 중.")


   asyncio.run(main())


.. toctree::
   :maxdepth: 1
   :glob:
   :hidden:
   :caption: Getting Started

   Introduction <self>
   Generate an application <tutorial_generate_key>
   Authenticate client <tutorial_authenticate>
   Receive and send message <tutorial_chat_bot>


.. toctree::
   :maxdepth: 2
   :glob:
   :hidden:
   :caption: API Reference

   API Reference <api>
   (Legacy) Basic API Reference <unofficial_basic>
   (Legacy) Chat API Reference <unofficial_chat>
   (Legacy) Manage API Reference <unofficial_manage>


.. toctree::
   :maxdepth: 1
   :glob:
   :hidden:
   :caption: Others

   Changelog <changelog>
   Migration from v1 to v2 <migration_v1_to_v2>