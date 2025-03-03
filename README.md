# chzzkpy

![PyPI - Version](https://img.shields.io/pypi/v/chzzkpy?style=flat)
![PyPI - Downloads](https://img.shields.io/pypi/dm/chzzkpy?style=flat)
![PyPI - License](https://img.shields.io/pypi/l/chzzkpy?style=flat)

파이썬 기반의 치지직(네이버 라이브 스트리밍 서비스)의 비공식 라이브러리 입니다.<br/>
An unofficial python library for [Chzzk(Naver Live Streaming Service)](https://chzzk.naver.com/).<br/>

* [공식 문서(한국어)](https://gunyu1019.github.io/chzzkpy/ko/)
* [Offical Documentation(English)](https://gunyu1019.github.io/chzzkpy/en/)

## Installation

**Python 3.10 or higher is required.**

```bash
# Linux/MacOS
python3 -m pip install chzzkpy

# Windows
py -3 -m pip install chzzkpy
```

To install the development version.
```bash
$ git clone https://github.com/gunyu1019/chzzkpy.git -b develop
$ cd chzzkpy
$ python3 -m pip install -U .
```

## Quick Example

`chzzkpy`를 사용한 예제는 [Examples](examples)에서 확인하실 수 있습니다.<br/>
아래는 간단한 예제입니다.

#### 챗봇 (Chat-Bot)
```py
from chzzkpy.offical import Client, Donation, Message, UserPermission

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
    authorization_url = client.generate_authorization_token_url(redirect_url="https://localhost", state="abcd12345")
    print(f"Please login with this url: {authorization_url}")
    code = input("Please input response code: ")

    user_client = await client.generate_user_client(code, "abcd12345")
    await user_client.connect(UserPermission.all())

asyncio.run(main())
```

#### 챗봇 (Chat-Bot / 비공식 API)

```py
from chzzkpy.chat import ChatClient, ChatMessage, DonationMessage

client = ChatClient("channel_id")


@client.event
async def on_chat(message: ChatMessage):
    if message.content == "!안녕":
        await client.send_chat("%s님, 안녕하세요!" % message.profile.nickname)


@client.event
async def on_donation(message: DonationMessage):
    await client.send_chat("%s님, %d원 후원 감사합니다." % (message.profile.nickname, message.extras.pay_amount))


# 챗봇 기능을 이용하기 위해서는 네이버 사용자 인증이 필요합니다.
# 웹브라우저의 쿠키 값에 있는 NID_AUT와 NID_SES 값으로 로그인을 대체할 수 있습니다.
client.run("NID_AUT", "NID_SES")
```


#### 방송인 검색

```py
import asyncio
import chzzkpy


async def main():
    client = chzzkpy.Client()
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
```

#### 팔로워 불러오기 (Get followers)

```py
import asyncio
import chzzkpy


async def main():
    client = chzzkpy.Client()

    # 채널 관리 기능을 이용하기 위해서는 네이버 사용자 인증이 필요합니다.
    # 웹브라우저의 쿠키 값에 있는 NID_AUT와 NID_SES 값으로 로그인을 대체할 수 있습니다.
    client.login("NID_AUT", "NID_SES")
    manage_client = client.manage("channel_id")

    followers = await manage_client.followers()
    if len(result) == 0:
        print("팔로워가 없습니다. :(")
        await client.close()
        return

    for user in result.data:
        print(f"{user.user.nickname}: {user.following.follow_date}부터 팔로우 중.")
    await client.close()

asyncio.run(main())
```

## Contributions 
`chzzkpy`의 기여는 언제든지 환영합니다!<br/>
버그 또는 새로운 기능은 `Pull Request`로 진행해주세요.
