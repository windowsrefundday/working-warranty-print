import gzip
import re
import shutil
import subprocess
import unittest
from typing import Dict, Any, Tuple, Optional

from interfaces.plugins.base import BaseWebPlugin
from interfaces.plugins.manager import WebPluginManager
from interfaces.plugins.mobile_camera_scanner import MobileCameraScannerPlugin, get_local_ip
from interfaces.web import WebInterfaceHandler


class DummyPlugin(BaseWebPlugin):
    @property
    def plugin_id(self) -> str:
        return "dummy_plugin"

    @property
    def name(self) -> str:
        return "Dummy Test Plugin"

    @property
    def icon(self) -> str:
        return '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><line x1="8.5" y1="2" x2="15.5" y2="2"/></svg>'

    def get_css(self) -> str:
        return ".dummy-class { color: red; }"

    def get_content_html(self, host: str, port: int, public_url: Optional[str] = None) -> str:
        return f'<div class="dummy">Host: {host}:{port}</div>'


    def get_javascript(self) -> str:
        return "console.log('dummy plugin');"

    def handle_api_get(self, path: str, query_params: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
        if path == "/api/plugins/dummy_plugin/test":
            return 200, {"ok": True}
        return None


class UnsafeMetadataPlugin(DummyPlugin):
    @property
    def plugin_id(self) -> str:
        return 'unsafe" onclick="alert(1)'

    @property
    def name(self) -> str:
        return "<script>alert(2)</script>"

    @property
    def short_name(self) -> str:
        return "<b>unsafe</b>"


class WebPluginTests(unittest.TestCase):
    def test_plugin_manager_registration_and_aggregation(self):
        manager = WebPluginManager()
        plugin = DummyPlugin()
        manager.register_plugin(plugin)

        self.assertEqual(len(manager.list_plugins()), 1)
        self.assertIn(".dummy-class", manager.get_all_css())
        self.assertIn("tab_dummy_plugin", manager.get_all_tab_buttons())
        self.assertIn("dummy_pluginSection", manager.get_all_content_html("127.0.0.1", 9191))
        plugin_javascript = manager.get_all_javascript()
        self.assertIn("<!-- Plugin: Dummy Test Plugin -->", plugin_javascript)
        self.assertIn("console.log('dummy plugin');", plugin_javascript)

    def test_plugin_manager_api_dispatch(self):
        manager = WebPluginManager()
        manager.register_plugin(DummyPlugin())

        res = manager.dispatch_api_get("/api/plugins/dummy_plugin/test", {})
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res[0], 200)
        self.assertEqual(res[1], {"ok": True})

        unhandled = manager.dispatch_api_get("/api/plugins/dummy_plugin/unknown", {})
        self.assertIsNone(unhandled)

    def test_plugin_navigation_escapes_untrusted_metadata(self):
        html = UnsafeMetadataPlugin().get_tab_button_html()

        self.assertNotIn('<script>alert(2)</script>', html)
        self.assertNotIn('id="tab_unsafe" onclick=', html)
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", html)
        self.assertIn("&lt;b&gt;unsafe&lt;/b&gt;", html)
        self.assertIn("&quot;", html)

    def test_mobile_camera_scanner_plugin(self):
        plugin = MobileCameraScannerPlugin()
        self.assertEqual(plugin.plugin_id, "mobile_camera_scanner")
        self.assertIn("Phone Camera Scanner", plugin.name)

        css = plugin.get_css()
        self.assertIn(".viewfinder-container", css)
        self.assertIn(".reticle-box", css)

        html = plugin.get_content_html("192.168.1.100", 9191)
        self.assertIn("mobileCameraVideo", html)
        self.assertIn("btnToggleCamera", html)
        self.assertIn("btnFlipCamera", html)
        self.assertIn("btnTorch", html)
        self.assertIn("autoPrintOnScan", html)
        self.assertIn("mobileManualSerial", html)

        js = plugin.get_javascript()
        self.assertIn("MobileCameraScannerPluginController", js)
        self.assertIn("BarcodeDetector", js)
        self.assertIn("BrowserMultiFormatReader", js)
        self.assertIn("/assets/zxing-browser-0.2.1.min.js", js)
        self.assertIn("window.ZXingBrowser", js)
        self.assertIn("this.zxingCanvas.width", js)
        self.assertIn("this.syncTogglePair('autoPrintOnScan'", js)
        self.assertIn("this.syncTogglePair('hapticFeedback'", js)
        self.assertIn("if (!this.hapticEnabled) return", js)
        self.assertIn("const autoPrint = this.autoPrintEnabled", js)
        self.assertIn("Math.floor(frameWidth * scale)", js)
        self.assertNotIn("const cropX", js)
        self.assertIn("/api/scan?serial=${encodeURIComponent(this.currentSheetSerial)}&print=true", js)
        self.assertNotIn("fetch(`/api/print`", js)
        self.assertIn("data.entitlements[0].service", js)
        self.assertIn("statusText.includes('ready')", js)
        self.assertIn("mobileManualSerialModal')?.addEventListener('keydown'", js)

        self.assertIn("left: 15%", css)
        self.assertIn("width: 70%", css)

        zxing_asset = (
            WebInterfaceHandler.STATIC_DIRECTORY
            / "zxing-browser-0.2.1.min.js.gz"
        )
        with gzip.open(zxing_asset, "rb") as asset_file:
            self.assertIn(b"ZXingBrowser", asset_file.read())

        status, payload = plugin.handle_api_get("/api/plugins/mobile_camera_scanner/info", {}) or (0, {})
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("success"))
        self.assertIn("local_ip", payload)

    def test_get_local_ip(self):
        ip = get_local_ip()
        self.assertIsInstance(ip, str)
        self.assertTrue(len(ip) > 0)

    def test_web_handler_renders_registered_plugins(self):
        html = WebInterfaceHandler.get_html_page(port=9191)
        self.assertIn("tab_mobile_camera_scanner", html)
        self.assertIn("mobile_camera_scannerSection", html)
        self.assertIn("mobileCameraVideo", html)
        self.assertIn("MobileCameraScannerPluginController", html)

    def test_generated_javascript_is_syntactically_valid(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is not installed")
        html = WebInterfaceHandler.get_html_page(port=9191)
        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL)
        inline_scripts = [script for script in scripts if script.strip()]
        result = subprocess.run(
            [node, "--check", "-"],
            input="\n".join(inline_scripts),
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
