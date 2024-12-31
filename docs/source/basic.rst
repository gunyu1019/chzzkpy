Basic Feature
=============

Client
------

.. autoclass:: chzzkpy.client.Client
   :members:

Enumerations
------------

.. autoclass:: chzzkpy.user.UserRole()
   :members:
   :undoc-members:

Channel
-------

.. autoclass:: chzzkpy.channel.PartialChannel()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.channel.Channel()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.channel.ChannelPersonalData()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Search
------
.. autoclass:: chzzkpy.search.SearchResult()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.search.TopSearchResult()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

User
----
.. autoclass:: chzzkpy.user.PartialUser()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.user.User()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Video
-----
.. autoclass:: chzzkpy.video.PartialVideo()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.video.Video()
   :members:
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Exceptions
----------
.. autoexception:: chzzkpy.error.LoginRequired()

.. autoexception:: chzzkpy.error.HTTPException()

.. autoexception:: chzzkpy.error.NotFound()