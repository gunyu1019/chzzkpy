import asyncio
import collections
import io
import threading

# pip install pydub
# pip install gTTS
# need ffmpeg, pyAudio or simpleaudio.
import gtts
import pydub
import pydub.playback

from chzzkpy.offical import Client, Message, UserPermission

# Configuration
client_id = "client_id"
client_secret = "client_secret"

loop = asyncio.get_event_loop()
client = Client(client_id, client_secret, loop=loop)
queue = collections.deque()


def _speak_with_text_to_speech():
    while len(queue):
        text = queue.popleft()
        tts = gtts.gTTS(text=text, lang="ko", slow=False)
        for generator in tts.stream():
            fp = io.BytesIO(generator)
            audio = pydub.AudioSegment.from_file(fp, format="mp3")
            pydub.playback.play(audio)

    global thread
    thread = threading.Thread(target=_speak_with_text_to_speech)


# Korean
# gTTS와 pydub는 synchronous-blocking (동기-블록)으로 처리됩니다.
# 함수가 호출되면, gTTS.stream() 함수와 pydub.play() 함수를 작동하는 과정에서 chat-client가 일시 정지할 수 있습니다.
# 결과적으로 웹 소켓은 항상 Keep-Alive가 필요하기 때문에, ConnectionClosed 예외를 초래할 수 있습니다.

# English
# gTTS and pydub is synchronous(blocking).
# When the method is called, chat-client pauses to process gTTS.stream() and pydub.play().
# As a result can cause ConnectionClosed (web socket always needs Keep-Alive)
thread = threading.Thread(target=_speak_with_text_to_speech)


@client.event
async def on_connect():
    print("Ready bot.")


@client.event
async def on_chat(message: Message):
    queue.append(message.content)
    if not thread.is_alive():
        thread.start()


async def main():
    authorization_url = client.generate_authorization_token_url(redirect_url="https://localhost", state="abcd12345")
    print(f"Please login with this url: {authorization_url}")
    code = input("Please input response code: ")

    user_client = await client.generate_user_client(code, "abcd12345")
    await user_client.connect(UserPermission(chat=True))


asyncio.run(main())
