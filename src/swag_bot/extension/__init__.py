"""Chrome extension bridge.

This package is a front end, like ``swag run``. It may call the public
factories and ``execute_goal``. It is not one of the owned core packages, and
those packages do not import it.
"""

from swag_bot.extension.ids import DEV_EXTENSION_ID, HOST_NAME

__all__ = ["DEV_EXTENSION_ID", "HOST_NAME"]
