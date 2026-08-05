from typing import List, Dict, Optional, Tuple, Any
from interfaces.plugins.base import BaseWebPlugin

class WebPluginManager:
    """
    Manager for discovering, registering, and orchestrating web interface plugins.
    """

    def __init__(self):
        self._plugins: Dict[str, BaseWebPlugin] = {}

    def register_plugin(self, plugin: BaseWebPlugin) -> None:
        """Register a new web plugin."""
        self._plugins[plugin.plugin_id] = plugin

    def get_plugin(self, plugin_id: str) -> Optional[BaseWebPlugin]:
        """Retrieve a registered plugin by ID."""
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> List[BaseWebPlugin]:
        """Return all registered plugins."""
        return list(self._plugins.values())

    def get_all_css(self) -> str:
        """Aggregate CSS from all registered plugins."""
        css_blocks = [f"/* Plugin: {p.name} */\n" + p.get_css() for p in self._plugins.values() if p.get_css()]
        return "\n".join(css_blocks)

    def get_all_tab_buttons(self) -> str:
        """Aggregate navigation tab buttons from all registered plugins."""
        return "\n".join(p.get_tab_button_html() for p in self._plugins.values())

    def get_all_content_html(self, host: str, port: int, public_url: Optional[str] = None) -> str:
        """Aggregate HTML views from all registered plugins."""
        views = []
        for p in self._plugins.values():
            views.append(f'<div id="{p.plugin_id}Section" class="plugin-section hidden">\n{p.get_content_html(host, port, public_url)}\n</div>')
        return "\n".join(views)


    def get_all_javascript(self) -> str:
        """Aggregate JavaScript scripts from all registered plugins."""
        js_blocks = [
            f"<!-- Plugin: {p.name} -->\n" + p.get_javascript()
            for p in self._plugins.values()
            if p.get_javascript()
        ]
        return "\n".join(js_blocks)

    def dispatch_api_get(self, path: str, query_params: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
        """Route API GET requests matching /api/plugins/<plugin_id>/... to the designated plugin."""
        if not path.startswith("/api/plugins/"):
            return None
        parts = path.strip("/").split("/")
        if len(parts) >= 3:
            plugin_id = parts[2]
            plugin = self.get_plugin(plugin_id)
            if plugin:
                return plugin.handle_api_get(path, query_params)
        return None

    def dispatch_api_post(self, path: str, body_data: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
        """Route API POST requests matching /api/plugins/<plugin_id>/... to the designated plugin."""
        if not path.startswith("/api/plugins/"):
            return None
        parts = path.strip("/").split("/")
        if len(parts) >= 3:
            plugin_id = parts[2]
            plugin = self.get_plugin(plugin_id)
            if plugin:
                return plugin.handle_api_post(path, body_data)
        return None
