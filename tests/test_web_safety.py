import unittest

from interfaces.web import WebInterfaceHandler


class WebSafetyTests(unittest.TestCase):
    def test_dynamic_values_are_escaped_before_inner_html_rendering(self):
        html = WebInterfaceHandler.get_html_page()

        self.assertIn("function escapeHtml(value)", html)
        self.assertIn("escapeHtml(val)", html)
        for field in (
            "data.vendor",
            "data.model",
            "data.serial",
            "data.status",
            "data.ship_date",
            "data.expiration_date",
            "data.source_confidence",
            "data.lookup_error",
        ):
            self.assertIn(f"escapeHtml({field})", html)
