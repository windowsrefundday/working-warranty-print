from interfaces.plugins.base import BaseWebPlugin
from interfaces.plugins.manager import WebPluginManager
from interfaces.plugins.mobile_camera_scanner import MobileCameraScannerPlugin, get_local_ip

__all__ = [
    "BaseWebPlugin",
    "WebPluginManager",
    "MobileCameraScannerPlugin",
    "get_local_ip",
]
