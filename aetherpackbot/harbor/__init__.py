"""Harbor: message-dock layer.

IM vendors are berths. Agents only see a Manifest.
HTTP/WS on one wire. No vendor SDKs.
"""

from aetherpackbot.harbor.manager import HarborMaster

__all__ = ["HarborMaster"]
