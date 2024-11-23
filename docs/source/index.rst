Introduction
============
| 파이썬 기반의 치지직(네이버 라이브 스트리밍 서비스)의 비공식 라이브러리 입니다.
| An unofficial python library for Chzzk(Naver Live Streaming Service).

**Feature**

* Chatting in live.
* Search broadcaster, live, video.
* Lookup a live of broadcaster.
* (WIP) Manage broadcast.

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

   $ git clone https://github.com/gunyu1019/chzzk_py
   $ chzzk_py
   $ python3 -m pip install -U .

Quick Example
-------------
This section is a simple example used in chzzpkpy.
You can see more examples at `Example Repository <https://github.com/gunyu1019/chzzkpy/tree/main/examples>`__ .

Searching broadcaster
`````````````````````

.. code-block:: python
   
   import asyncio
   import chzzkpy

   loop = asyncio.get_event_loop()
   client = chzzkpy.Client(loop=loop)

   async def main():
      result = await client.search_channel("건유1019")
      if len(result) == 0:
         print("검색 결과가 없습니다 :(")
         return
      print(result[0].name)
      print(result[0].id)
      print(result[0].image)
      await client.close()

   loop.run_until_complete(main())



Chat Bot
````````

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


.. toctree::
   :maxdepth: 2
   :glob:
   :hidden:
   :caption: Table of Contents

   Introduction <self>
   Basic Feature <basic>
   Chat Feature <chat>