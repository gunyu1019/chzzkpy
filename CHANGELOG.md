## v2.1.0 - Aug 1st, 2025
* **(Breaking Change)** Modify offical pacakge to default package, and unoffical package from default package.
  ```py
  # Before (~v2.0.6)
  from chzzkpy.chat import ChatClient
  from chzzkpy.offical import Client

  # After (v2.1.0~)
  from chzzkpy.unoffical.chat import ChatClient
  from chzzkpy import Client
  ```
* Add restriction related feature. ([Restriction API Reference](https://chzzk.gitbook.io/chzzk/chzzk-api/restriction))
* Add `on_subscription` event to receive new subscriber event.
  ```py
  @client.event
  async def on_subscription(subscription):
    print(f"New subscriber! : {subscription.subscriber_name} / {subscription.tier_name} / {subscription.month}")
  ```
* Add `UserPermission.subscription` flag to register `subscription` event and receive `on_subscription` event.
* Add `Client.login()` method for comfortable experience.
  This method temporarily opens an HTTP server to perform OAuth2 authentication.
  ```py
  # Before
  authorization_url = client.generate_authorization_token_url(redirect_url="https://localhost", state="abcd12345")
  print(f"Please login with this url: {authorization_url}")
  code = input("Please input response code: ")

  user_client = await client.generate_user_client(code, "abcd12345")

  # After (Recommended)
  user_client = await client.login()  # Open a temporary HTTP(s) server and open a web browser for authentication.
  ```
* Add `UserClient.get_followers` method to read followers of channel
* Add `UserClient.get_subscribers` method to read subscribers of channel.
* Add `UserClient.get_channel_administrator` method to read administrator of channel.
* Add `verified_mark` attribute in Channel data model.
* Add `slow_mode` and `emoji_mode` parameter in `UserClient.set_chat_setting` method.
* [Fix] Invaild HTTP method called in `get_channel`, `get_category` method.
* [Fix] (chzzkpy.chat) Modify condition of connection exception.

## v2.0.6 - Jun 25th, 2025
* [Fix] (Engine) Missing length, byteorder arguments of to_bytes method in Payload.encode() method.

## v2.0.5 - Mar 28th, 2025
* [Fix] (chzzpky.chat) Add 2 types of ChatConnectFailed exception to handle exceptional situations.
* [Fix] (chzzpky.chat) Add exception condition in confirm_live_status method to handle exceptional situations.
* [Fix] (chzzpky.chat) Missing required body parameter in NaverGameChatSession http client.
* [Fix] (chzzpky.chat) Initial connect method always called, when new gateway opened.
* [Fix] (chzzkpy.offical) Missing typing.Self feature in python 3.10 version. 

## v2.0.4 - Mar 16th, 2025
* [Fix] Invaild parameter name called in offical.Donation

## v2.0.3 - Mar 9th, 2025
* [Fix] Invaild client-id, client-secret attribute called in user client

## v2.0.2 - Mar 9th, 2025
* Add refresh access token method in client.
* [Fix] Invaild calling attribute name in refresh user client method

## v2.0.1 - Mar 8th, 2025
* Add `quantity`, and other attribute in `SubscriptionGiftExtra` to receive multiple subscriptions gift
* Add `viewer_badge` attribute in `Profile`
* Add `nickname_color`, and `subscription` attribute in `StreamingProperty`
* Add validation in defining UserClient part to check correcting access token
* [Fix] Invaild calling method  (geturl) => (__str__) in https://github.com/gunyu1019/chzzkpy/issues/65

## v2.0.0 - Mar 7th, 2025
* Support offical API provided by [Chzzk Developer Center](https://developers.chzzk.naver.com/)
  * Support Session feature to handle donation, message.
  * Support Chat Section feature to send message, send announcement, or setup chatting.
  * Support User Section feature to get self-channel info
  * Support Authorization Section feature to authentic channel.
  * Support Channel Section feature to search channel with an unique id, or setup self-channel
  * Support Live Section feature to search live
  * Support Category Section featrue to gather categories.
* Apply indepentent gateway configured socket.io and engine.io protocol in python environment.
* Support Multiple-Connection Session feature. (Max Client Session: 10, Max User Session: unlimited)

## v1.2.0 - Mar 3rd, 2025
* Add `on_subscription_gift` event to handle subscription gift.
* Add `SubscriptionGiftMessage`, `SubscriptionGiftExtra` data class.
* Add `approve` and `reject` method in `DonationMessage` to response Mission Donation.
  ```py
  async def on_donation(donation: chzzkpy.DonationMessage):
      if donation.extras.donation_type != "MISSION":
          return
      await donation.approve()
      return 
  ```

## v1.1.7 - Feb 16th, 2025
* Apply new restrict feature to chzzkpy package. (add days, reason parameter)
* Add edit restrict method
* RestrictUser data class extends ParticleUser.
* [Fix] (Temporary Action) An Exception was raised when ManageClient.subcribers method called without filter parameter.

## v1.1.6 - Feb 6th, 2025
* [Fix] Invaild parameter name to filter subscribers with nickname.
* [Fix] Add `has_login` condition at Message.model_validate_with_client classmethod to cause LoginRequired Exception when client didn't logined.

## v1.1.5 - Feb 4th, 2025
* [Fix] Invaild usage parameter at ManageClient.subcribers method.
* [Fix] Missing attribute exception(in anonymous donation) at MissingDonation

## v1.1.4 - Jan 28th, 2025
* [Fix] Missing loginable attribute at the live_status, live_detail method.

## v1.1.3 - Jan 13st, 2025
* Add message for developer-experience at `ChatConnectFailed` Exception.

## v1.1.2 - Jan 11st, 2025
(Emergency Update)
* [Fix] Missing some commit in https://github.com/gunyu1019/chzzkpy/issues/40

## v1.1.1 - Jan 11st, 2025
* Add `on_mission_cost_update` event
* Add MissionParticipationDonation data-class to handle `on_mission_cost_update`
* Add missiong attribute at `BaseDonation`, `MissionDonation` in https://github.com/gunyu1019/chzzkpy/issues/37

## v1.1.0 - Jan 1st, 2025
* Implement channel management feature.
   * Get chat activity count
   * Add temporary restrict 
   * Add/Delete restrict
   * Manage channel permission
   * Manage Stream
   * Prohibit Word
   * Manage video and replay video
   * Manage restrict-activity user and unrestrict-activity-request.
   * Collect following user and, subscription user.
* Add interactive feature at PartialUser classes. (restrict, role, chat activity count)
* Add interactive feature at Message(extends NoticeMessage, SubscriptionMessage, DonationMessage ... etc)
* Add `profile_card` method at Chat Client
* Add PartialVideo class (for management feautre.)
* Move UserRole enumeration class to basic. (for management feature.)
* [Fix] SystemExtraParameter.register_chat_profile and SystemExtraParameter.target_profile can be None.
* [Fix] Duplicated attribute (Profile.activity_badges)

## v1.0.4 - Nov 23th, 2024
- Add `on_broadcast_open` / `on_broadcast_close` event handler
- Add `close` method at `gateway.py`
- When a client used ChatClient, live_status, live_detail method didn't need channel_id argument. (Enhance Developer Experience)
- Add Package Document ([Korean](https://gunyu1019.github.io/chzzkpy/ko/), [English](https://gunyu1019.github.io/chzzkpy/en/))
- [Fix] Add chat reconnection condition. 
  (When a streammer created a new broadcast, the chat_channel_id will regenerated.)

## v1.0.3 - Nov 10th, 2024
* Add `on_mission_pending` event (When a user request a new mission, the event handler is called.)
* Add `on_mission_rejected/approved` event (When a broadcaster approves or rejects a new mission, the event handler is called.)
* Add `on_mission_complete` event (When a broadcaster complete a mission, the event handler is called.)
* Add `on_subscription` event.
* Divide data class struction `donation.py` from `message.py` 
* [Fix] Wrong literial type (MissionDontationExtra)

## v1.0.2 - Oct 4th, 2024
* Change LoginRequired Exception message.
* Add ChatConnectFailed Exception, when LiveStatus content is None. 
  (Addition Description: the broadcaster isn't on air for a long time or anytime.)
* Add HTTPException and NotFound Exception for more experience.

## v1.0.1 - Jul 23th, 2024
* [Fix] Invalid `emojis` field
* Update python dependience packages

## v1.0.0 - Jun 6th, 2024
* Impelement search feature (channel, live, video)
* Impelement autocomplete feature
* Impelement manage feature about chat message.
* Impelement channel data-model
* Impelement video data-model 
* [Fix] Skipped return on notice event.