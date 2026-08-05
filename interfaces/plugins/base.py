from abc import ABC, abstractmethod
import html
import json
from typing import Optional, Tuple, Dict, Any

class BaseWebPlugin(ABC):
    """
    Abstract base class for web interface plugins.
    Allows modular extension of web UI, styling, client scripts, and custom API endpoints.
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique identifier for the plugin (e.g. 'mobile_camera_scanner')."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name for the plugin."""
        pass

    @property
    def icon(self) -> str:
        """Trusted built-in SVG markup representing the plugin."""
        return '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v8"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/></svg>'

    @property
    def short_name(self) -> str:
        """Short display name for mobile bottom navigation bar."""
        return self.name

    def get_css(self) -> str:
        """Return custom CSS to be injected into the main page head."""
        return ""

    def get_tab_button_html(self) -> str:
        """Return HTML for the navigation tab button."""
        plugin_id = html.escape(self.plugin_id, quote=True)
        javascript_id = html.escape(json.dumps(self.plugin_id), quote=True)
        name = html.escape(self.name)
        short_name = html.escape(self.short_name)
        return (
            f'<button id="tab_{plugin_id}" class="tab-btn" '
            f'onclick="switchTab({javascript_id})">{self.icon} '
            f'<span class="tab-label-full">{name}</span>'
            f'<span class="tab-label-short">{short_name}</span>'
            f'</button>'
        )

    @abstractmethod
    def get_content_html(self, host: str, port: int, public_url: Optional[str] = None) -> str:
        """Return HTML content for the main plugin view container."""
        pass


    def get_javascript(self) -> str:
        """Return custom JavaScript to be injected before </body>."""
        return ""

    def handle_api_get(self, path: str, query_params: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
        """
        Handle plugin-specific GET requests (e.g., /api/plugins/<plugin_id>/...).
        Returns (http_status_code, json_payload_dict) or None if unhandled.
        """
        return None

    def handle_api_post(self, path: str, body_data: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
        """
        Handle plugin-specific POST requests (e.g., /api/plugins/<plugin_id>/...).
        Returns (http_status_code, json_payload_dict) or None if unhandled.
        """
        return None
