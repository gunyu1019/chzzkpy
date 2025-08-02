Generate an application
=======================
To use the CHZZK API with chzzkpy package, we need to register an application.
The process of registering for the app is very simple.

1. Login to the `CHZZK Developer Center <https://developers.chzzk.naver.com/>`_ page with your Naver account.
    .. image:: _static/image/tutorial_register_application_1.png

2. Click “내 서비스” to navigate to the `application <https://developers.chzzk.naver.com/application>`_ page.

3. Click “애플리케이션 등록하기” button.

4. Fill in the text fields.
    .. image:: _static/image/tutorial_register_application_2.png
    
    * 애플리케이션 ID: Application's unique ID
    * 애플리케이션 이름: The name of application
    * 로그인 리디렉션 URL: The redirect URL following the OAuth2 process
        (To authenticate with a temporary web server using the :class:`Client.login <chzzkpy.client.Client.login>` method, enter “http://localhost:8080/”.)
    * API Scopes: Permissions that this application can access.
        (For example, to send and receive messages, this application requires “채팅 메시지 조회” and “채팅 메시지 쓰기”.)

5. Click “등록” to register the new application.

6. Copy “클라이언트 ID” and “클라이언트 Secret” to authenticate :class:`chzzkpy.Client<chzzkpy.Client>`
    .. image:: _static/image/tutorial_register_application_3.png


    .. code-block:: python

        import chzzkpy

        client_id = "CLIENT ID"
        client_secret = "CLIENT SECRET"
        client = chzzkpy.Client(client_id, client_secret)