"""
Platform Layer - Messaging platform adapters.

Manages connections to various messaging platforms like Telegram, Discord, etc.
"""

from aetherpackbot.harbor.manager import HarborMaster
from aetherpackbot.platforms.manager import PlatformManager

__all__ = [
    "HarborMaster",
    "PlatformManager",
]
