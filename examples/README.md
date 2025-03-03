# Examples
`chzzkpy`를 활용한 예제를 나열해보았습니다.

### [Text-To-Speech Chat](chat_tts.py)
사용자가 입력한 채팅을 Text-To-Speech(TTS)를 사용하여 읽어줍니다.

1. `channel_id`에 자신의 치지직 채널 ID를 채웁니다.
2. 아래의 패키지를 모두 설치해주세요.
   * gTTS (`pip install gTTS`)
   * pydub (`pip install pydub`)
   * ffmpeg 또는 pyAudio, simpleaudio 중 하나 (`pip install pyAudio`, `pip install simpleaudio`)

### [(비공식API) Discord Webhook](discord_webhook.py)
사용자가 입력한 채팅을 디스코드 채팅방에 실시간으로 반영됩니다.

<table>
  <tr>
    <th>치지직</th>
    <th>디스코드</th>
  </tr>
  <tr>
    <td><img src="https://github.com/gunyu1019/chzzk_py/assets/16767890/66197543-5e51-4ab7-85b2-1f3508f49248" height="80px" /></td>
    <td><img src="https://github.com/gunyu1019/chzzk_py/assets/16767890/5f9a5a81-28d0-451c-958f-a0f5ad4e0caa" height="80px" /></td>
  </tr>
</table>

사용전, 아래의 과정이 필요합니다.
1. `channel_id`에 자신의 치지직 채널 ID를 채웁니다.
2. 패키지 discord.py (`pip install discord.py`)를 설치합니다.
3. 채팅 목록을 불러올 채널에서 `채널 편집 > 연동 > 웹후크`로 이동합니다.
4. `새 웹후크`를 눌러 웹후크를 하나 생성합니다. 
5. 웹후크 URL를 복사하여 `webhook_url`를 채웁니다.

### [Spotify Playlist Bot](spotify_playlist_bot.py)
명령어를 사용하여 스포티파이 재생목록에 추가할 수 있습니다.<br/>
ex. `$선곡 [추가할 노래]`<br/>
<img src="https://github.com/gunyu1019/chzzk_py/assets/16767890/39f4d428-5085-4cff-9abc-c7cd7cd1e15a" width="40%" />

추가할 노래는 Spotify에서 검색이 되어야 합니다.

시청자는 명령어를 사용하여 스트리머의 음악을 선곡할 수 있습니다.

사용전, 아래의 과정이 필요합니다.
1. `channel_id`에 자신의 치지직 채널 ID를 채웁니다.
2. 패키지 spotipy (`pip install spotipy`)를 설치합니다.
3. [대시보드](https://developer.spotify.com/dashboard)에서 스포티파이 개발용 애플리케이션을 만듭니다.<br/>
   (이때, redirect_url는 임의 설정된 `http://localhost:8888/redirect`로 해주는 것이 좋습니다.)
4. `client_id`, `client_secrect`, `redirect_url`를 모두 채웁니다.
5. 음악을 재생할 스포티파이 클라이언트를 활성화합니다. (ex. 안드리이드 애플리케이션)
