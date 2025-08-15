(Legacy) Basic API Reference
============================

Client
------

.. autoclass:: chzzkpy.unofficial.client.Client
   :members:
   :member-order: groupwise

Enumerations
------------

.. autoclass:: chzzkpy.unofficial.user.UserRole()
   :members:
   :member-order: groupwise
   :undoc-members:

Channel
-------

.. autoclass:: chzzkpy.unofficial.channel.PartialChannel()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.channel.Channel()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.channel.ChannelPersonalData()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Search
------
.. autoclass:: chzzkpy.unofficial.search.SearchResult()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:
   :show-inheritance:

.. autoclass:: chzzkpy.unofficial.search.TopSearchResult()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

User
----
.. autoclass:: chzzkpy.unofficial.user.PartialUser()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.user.User()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Video
-----
.. autoclass:: chzzkpy.unofficial.video.PartialVideo()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

.. autoclass:: chzzkpy.unofficial.video.Video()
   :members:
   :member-order: groupwise
   :exclude-members: model_computed_fields, model_config, model_fields, model_post_init
   :undoc-members:

Exceptions
----------
.. autoexception:: chzzkpy.unofficial.error.LoginRequired()

.. autoexception:: chzzkpy.unofficial.error.HTTPException()

.. autoexception:: chzzkpy.unofficial.error.NotFoundException()