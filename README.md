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


## Migration from v1 to v2
`chzzkpy`는 `v2`부터 [치지직 개발자센터](https://developers.chzzk.naver.com/)에서 제공하는 API를 지원합니다.
비공식 API를 더 이상 이용하지 못하는 것은 아닙니다.<br/> 
치지직 개발자센터에서 제공하는 API 중에는 미션 후원을 수신 받을 수 없는 등의 부족한 부분이 상당히 많습니다.<br/>
네이버 측에서는 공식으로 비공식 API 사용하는 것을 허락하지 않았으며, 그렇다고 비공식 API를 사용한다고 제지한다고 하지않는다고 공식 회신을 받았습니다..<br/>
어느 정도 네이버 측의 답변이며 비공식 API 이용과정에서 비정상적인 요청이 있을 경우 네이버 계정 보호조치가 이루어질 수 있습니다.<br/>
이 부분에 대해서 패키지 개발자는 어떠한 책임도 져드릴 수 없습니다.<br/><br/>
개인용 채팅봇이 아닌 이상 최대한 공식 API를 사용하는 것을 권장하고 싶습니다.<br/>
공식 API와 비공식 API는 완전히 다른 패키지지만, 최대한 개발 환경을 고려하여 비슷하게 만들도록 노력하였습니다.<br/><br/>
아래에 기재된 내용은 v1(비공식 API)에서 v2(공식 API)로 주요 마이그레이션 과정을 서술하였습니다.<br/>

* **패키지 추가**
    공식 API는 비공식 API와 달리 별도의 패키지로 구성되어있습니다.
    따라서 공식 API를 이용하기 위해서는 아래와 같이 호출하셔야 합니다.
    ```py
    # Before
    from chzzkpy.chat import ChatClient

    # After
    from chzzkpy.offical import Client
    ```
    
    이전에 이슈에서 공지사항으로 게재했던 것([내용](https://github.com/gunyu1019/chzzkpy/issues/42#issuecomment-2661430481))과 같이 `chzzkpy.offical` 패키지가 `chzzkpy`로 대체될 예정이긴 합니다.
    반대로 `chzzkpy`는 더 이상 지원하지 않거나, `chzzkpy.unoffical`로 대체될 예정입니다.

* **클라이언트 인증** ([Reference](https://chzzk.gitbook.io/chzzk/chzzk-api/authorization))<br/>
    `v1`는 네이버 송.수신 중에 입력되는 `NID_AUT`와 `NID_SES` 쿠키로 인증을 합니다. <br/>
    반면에 `v2 (공식API)`는 [치지직 개발자센터](https://developers.chzzk.naver.com/)에서 발급받은 `client_id`와 `client_secret`으로 인증을 합니다.
    ```py
    # Before
    client = ChatClient()
    client.login("NID_AUT", "NID_SES")

    # After
    client = Client(client_id, client_secret)
    ```

    채팅을 수신받거나, 방송 정보를 설정하는 등의 채널 권한이 필요한 기능은 사용자 인증 과정이 필요합니다.<br/>
    이때는 `client.generate_authorization_token_url`와 `client.generate_user_client` 메소드를 이용하여 사용자 인증을 진행해야합니다.

    ```py
    async def authentic_user():
        # OAuth2 로그인 방식과 동일하게 진행됩니다.
        authorization_url = client.generate_authorization_token_url(redirect_url="https://localhost", state="abcd12345")
        print(f"Please login with this url: {authorization_url}")
        code = input("Please input response code: ")

        user_client = await client.generate_user_client(code, "abcd12345")

        # API Scope에 "유저 정보 조회"가 있다면 로그인한 사용자의 채널을 조회할 수 있습니다.
        # await user_client.fetch_self()
        print(user_client.channel_id)
    ```

    인증을 성공하였다면, `UserClient` 형태의 유저 정보를 담고 있는 클라이언트를 반환받습니다. <br/>
    클라이언트를 이용하여 채널에 필요한 기능을 API Scope에 따라 이용할 수 있습니다.<br/>

* **이벤트 수신**<br/>
    공식 API에서는 후원(텍스트, 영상)과 채팅을 수신받을 수 있지만, 이들을 수신하기 위한 이벤트 구독 과정이 필요합니다.<br/>
    `v2`에서는 `connect()` 메소드에서 `UserPermission`을 입력받아 이벤트를 구독할 수 있습니다.<br/>
    
    ```py
    permission_type1 = UserPermission.all()  # 채팅, 후원 이벤트를 모두 수신받습니다.
    permission_type2 = UserPermission(chat=True)  # 채팅 이벤트만 수신받습니다.
    permission_type3 = UserPermission(donation=True)  # 후원 이벤트만 수신받습니다.

    await client.connect(permission=permission_type1)
    # 또는 await UserClient.subscription(permission=permission_type1, ...) 메소드를 이용하여 수신받도록 설정할 수 잇습니다.
    ```

* **다중 채널 연결 지원**<br/>
    `chzzkpy` v2에서는 다중 채널 연결을 지원합니다. 따라서, 하나의 클라이언트로 여러 채널을 수신받거나 메시지를 보낼 수 있습니다.<br/>
    만약에 다중 채널을 연결할 경우, `connect` 메소드의 `addition_connect` 매개변수를 아래와 같이 사용하여 다중 연결을 할 수 있습니다.<br/>

    ```py
    @client.event
    async def on_chat(message):
        # user_client1 에서 수신받은 채팅, user_client2 에서 수신받은 채팅 모두 수신이 가능합니다.
        # 채널을 보낸 곳을 기준으로 "응답" 메시지를 회신합니다.
        await message.send("응답")

    async def main():
        authorization_url = client.generate_authorization_token_url(redirect_url="https://localhost", state="abcd12345")
        print(f"Please login with this url: {authorization_url}")
        code1 = input("Please input response code1: ")
        code2 = input("Please input response code2: ")

        user_client1 = await client.generate_user_client(code1, "abcd12345")
        user_client2 = await client.generate_user_client(code2, "abcd12345")

        await user_client1.connect(UserPermission.all(), addition_connect=True)
        await user_client2.connect(UserPermission.all()) 
    ```

    `addition_connect` 매개변수를 활성화하면 이벤트 수신을 백그라운드에서 진행하게 됩니다.<br/>
    `user_client1`의 이벤트는 백그라운드에서 수신받고, `user_client2`의 이벤트는 메인에서 블록되어 수신받을 수 있습니다.

    필요에 따라 `addition_connect` 매개변수를 이용하여 메인 블록을 다른 곳에 활용할 수도 있습니다.<br/>
    다만, 메인 블록이 종료되면 백그라운드도 모두 종료되어 메인 블록이 대기할 수 있도록 설정해야 합니다.

궁금하시거나, 문의사항이 있으시면 [Developer Space(디스코드)](https://discord.gg/YWUvFQ69us) 또는 [이슈(Issue)](https://github.com/gunyu1019/chzzkpy/issues)를 이용하시면 적극 도와드리도록 하겠습니다.

## Contributions 
`chzzkpy`의 기여는 언제든지 환영합니다!<br/>
버그 또는 새로운 기능은 `Pull Request`로 진행해주세요.
