Authenticate Client
===================
API authentication is required to use some features of the chzzkpy package.

Client
------
You must complete `Generate an Application`.

Once the process is complete, the client can be authenticate using the `Client ID` and `Client secret`.

.. code-block:: python

    import chzzkpy

    client_id = "CLIENT ID"
    client_secret = "CLIENT SECRET"
    client = chzzkpy.Client(client_id, client_secret)

User Client
-----------

.. note::
    In order to authenticate the :class:`UserClient<chzzkpy.client.UserClient>`, the :class:`Client<chzzkpy.client.Client>` must be authenticated.

UserClient authentication is based on the OAuth2 process.
This is two methods to authenticate UserClient.

1. Using :class:`generate_authorization_token_url<chzzkpy.client.Client.generate_authorization_token_url>` and :class:`generate_user_client<chzzkpy.client.Client.generate_user_client>` methods.
   
   .. code-block:: python

        authorization_url = client.generate_authorization_token_url(
          redirect_url="https://localhost:8080/", 
          state="abcd12345"
        )
        print(f"Please login with this url: {authorization_url}")
        code = input("Please input response code: ")

        user_client = await client.generate_user_client(code, "abcd12345")

        # await user_client.fetch_self()
        print(user_client.channel_id)
       
   Get the URL for OAuth2 authentication through :class:`generate_authorization_token_url<chzzkpy.client.Client.generate_authorization_token_url>` method.
   If third-party authentication is successful, it is returned with a `code` query in the redirection URL.

   To authenticate, enter the `code` in the redirect URL into the :class:`generate_user_client<chzzkpy.client.Client.generate_user_client>` method.

2. Using :class:`Client.login<chzzkpy.client.Client.login>` method with temporary HTTP server.
   
   .. code-block:: python

        user_client = await client.login()
   
   When :class:`client.login <chzzkpy.client.Client.login>` method is executed, a temporary web server for authentication is launched and a browser opens.
   Once authentication is complete, the web server terminates and returns :class:`UserClient <chzzkpy.client.UserClient>`.

(Legacy) Client / ChatClient
----------------------------

An unofficial API-based :class:`client<chzzkpy.unofficial.client.Client>` use `NID_AUT` and `NID_SES` cookies for authentication.
This cookie is used to verify your Naver account, so it should not be shared with others.

.. code-block:: python

    import chzzkpy.unofficial

    NID_AUT = "Authenticate Cookie key"
    NID_SES = "Session Cookie key"

    client = chzzkpy.unofficial.Client()
    client.login(NID_AUT, NID_SES)