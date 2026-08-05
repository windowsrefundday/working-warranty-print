import http.server
import gzip
import hmac
import ipaddress
import json
import re
import secrets
import socketserver
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Optional

from core.engine import WarrantyEngine
from core.label_formatters.tspl import LabelProfile, TSPLLabelFormatter
from core.printers.tsc_connector import (
    TSCPrinterConnector,
    load_saved_profile,
    save_profile_to_file,
)
from interfaces.profile_service import PrinterProfileService
from interfaces.plugins import (
    WebPluginManager,
    MobileCameraScannerPlugin,
    get_local_ip,
)


class ConcurrentWebServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Serve independent browser and vendor-lookup requests concurrently."""

    allow_reuse_address = True
    daemon_threads = True


class WebInterfaceHandler(http.server.BaseHTTPRequestHandler):
    SESSION_COOKIE_NAME = "warranty_pair"
    MAX_POST_BODY_BYTES = 64 * 1024
    MAX_SERIAL_LENGTH = 64
    REMOTE_RATE_LIMIT_REQUESTS: int = 30
    REMOTE_RATE_LIMIT_WINDOW_SECONDS = 60.0
    MAX_TRACKED_REMOTE_CLIENTS: int = 4096
    STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
    engine: Optional[WarrantyEngine] = None
    profile_service = PrinterProfileService()
    plugin_manager = WebPluginManager()
    plugin_manager.register_plugin(MobileCameraScannerPlugin())
    server_port: int = 9191
    pairing_token: Optional[str] = None
    tsc_profile_lock = threading.RLock()
    PAIR_QUERY_PATTERN = re.compile(r"([?&]pair=)[^&\s]*", re.IGNORECASE)
    SERIAL_QUERY_PATTERN = re.compile(r"([?&]serial=)[^&\s]*", re.IGNORECASE)
    _rate_limit_lock = threading.Lock()
    _remote_request_times: dict[str, list[float]] = {}

    def log_message(self, format: str, *args) -> None:
        redacted_args = tuple(
            self.SERIAL_QUERY_PATTERN.sub(
                r"\1[REDACTED]",
                self.PAIR_QUERY_PATTERN.sub(r"\1[REDACTED]", str(arg)),
            )
            for arg in args
        )
        super().log_message(format, *redacted_args)

    def do_GET(self):
        assert self.engine is not None, "WebInterfaceHandler.engine must be initialized"
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if self._remote_request_is_rate_limited():
            self._send_rate_limited()
            return

        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self._send_security_headers()
            self.end_headers()
            return
        if parsed.path == "/" and self._establish_remote_pairing(qs):
            return
        if not self._request_is_authorized():
            self.send_json(
                {"error": "Remote access requires the secure QR pairing link."},
                status=403,
            )
            return

        plugin_res = self.plugin_manager.dispatch_api_get(parsed.path, qs)
        if plugin_res is not None:
            self.send_json(plugin_res[1], status=plugin_res[0])
            return

        if parsed.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(self.get_html_page().encode('utf-8'))

        elif parsed.path == "/assets/zxing-browser-0.2.1.min.js":
            self._send_static_asset(
                "zxing-browser-0.2.1.min.js.gz",
                "text/javascript; charset=utf-8",
                content_encoding="gzip",
            )

        elif parsed.path in ('/api/profile', '/api/printer/profile', '/api/printer/status'):
            self.send_json(self._get_printer_status_payload())

        elif parsed.path == '/api/scan':
            serial = qs.get('serial', [''])[0]
            should_print = qs.get('print', ['false'])[0].lower() == 'true'

            bounded_serial = self._bounded_serial(serial)
            if bounded_serial is None:
                return
            serial = bounded_serial

            ee_record = self.engine.parse_ee_scan(serial)
            if ee_record is not None:
                print_res = None
                if should_print:
                    with self.tsc_profile_lock:
                        res = self.engine.print_ee_label(ee_record)
                    print_res = {
                        'success': res.success,
                        'printer': res.printer_name,
                        'output_path': res.output_path,
                        'error': res.error_message,
                    }
                self.send_json({
                    'mode': 'ee',
                    'serial': ee_record.ee_number,
                    'ee_number': ee_record.ee_number,
                    'vendor': 'Internal',
                    'model': 'EE Label',
                    'status': 'Ready',
                    'ship_date': '',
                    'expiration_date': '',
                    'source_confidence': 'INTERNAL EE SCAN',
                    'lookup_error': None,
                    'lookup_ms': 0,
                    'entitlements': [],
                    'print_result': print_res,
                })
                return

            lookup_started = time.perf_counter()
            asset = self.engine.lookup_asset(serial)
            lookup_ms = round((time.perf_counter() - lookup_started) * 1000)
            print_res = None
            if should_print:
                with self.tsc_profile_lock:
                    res = self.engine.print_asset_label(asset)
                print_res = {
                    'success': res.success,
                    'printer': res.printer_name,
                    'output_path': res.output_path,
                    'error': res.error_message,
                }

            self.send_json({
                'mode': 'warranty',
                'serial': asset.serial_number,
                'vendor': asset.vendor.value,
                'model': asset.model_name,
                'status': asset.warranty_status,
                'ship_date': asset.ship_date,
                'expiration_date': asset.expiration_date,
                'source_confidence': asset.source_confidence.value,
                'lookup_error': asset.lookup_error,
                'lookup_ms': lookup_ms,
                'entitlements': [{'service': e.service_name, 'status': e.status} for e in asset.entitlements],
                'print_result': print_res,
            })

        elif parsed.path == '/api/export':
            csv_str = self.engine.export_csv_string()
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv')
            self.send_header('Content-Disposition', 'attachment; filename="Warranty_Audit.csv"')
            self.send_header('Cache-Control', 'no-store')
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(csv_str.encode('utf-8'))

        else:
            self.send_error(404, "Page Not Found")

    def do_POST(self):
        assert self.engine is not None, "WebInterfaceHandler.engine must be initialized"
        parsed = urllib.parse.urlparse(self.path)
        if self._remote_request_is_rate_limited():
            self._send_rate_limited()
            return
        if not self._request_is_authorized():
            self.send_json(
                {"error": "Remote access requires the secure QR pairing link."},
                status=403,
            )
            return
        raw_content_len = self.headers.get('Content-Length')
        if raw_content_len is None:
            self.send_json({'error': 'Content-Length is required'}, status=400)
            return
        try:
            content_len = int(raw_content_len)
        except (TypeError, ValueError):
            self.send_json({'error': 'Malformed Content-Length'}, status=400)
            return
        if content_len < 0:
            self.send_json({'error': 'Malformed Content-Length'}, status=400)
            return
        if content_len > self.MAX_POST_BODY_BYTES:
            self.send_json({'error': 'Request body is too large'}, status=413)
            return
        post_body_bytes = self.rfile.read(content_len)
        if len(post_body_bytes) != content_len:
            self.send_json({'error': 'Incomplete request body'}, status=400)
            return
        try:
            post_body = post_body_bytes.decode('utf-8')
            data = json.loads(post_body) if post_body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({'error': 'Invalid JSON payload'}, status=400)
            return
        if not isinstance(data, dict):
            self.send_json({'error': 'JSON payload must be an object'}, status=400)
            return

        plugin_res = self.plugin_manager.dispatch_api_post(parsed.path, data)
        if plugin_res is not None:
            self.send_json(plugin_res[1], status=plugin_res[0])
            return

        if parsed.path in ('/api/profile', '/api/printer/profile'):
            self._handle_save_profile(data)
        elif parsed.path in ('/api/calibrate', '/api/printer/calibrate'):
            self._handle_calibrate(data)
        elif parsed.path in ('/api/preview', '/api/printer/preview'):
            self._handle_preview(data)
        elif parsed.path in ('/api/toggle-printer', '/api/printer/toggle'):
            self._handle_toggle_printer(data)
        else:
            self.send_error(404, "Endpoint Not Found")


    def send_json(self, data, status=200, headers: Optional[dict[str, str]] = None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _send_rate_limited(self) -> None:
        self.send_json(
            {"error": "Too many requests. Please try again later."},
            status=429,
            headers={"Retry-After": "60"},
        )

    def _bounded_serial(self, serial: object) -> Optional[str]:
        if not isinstance(serial, str):
            self.send_json({'error': 'Serial number is required'}, status=400)
            return None
        serial = serial.strip()
        if not serial:
            self.send_json({'error': 'Serial number is required'}, status=400)
            return None
        if len(serial) > self.MAX_SERIAL_LENGTH:
            self.send_json({'error': 'Serial number is too long'}, status=400)
            return None
        return serial

    def _bounded_test_serial(self, data: dict) -> Optional[str]:
        if "test_serial" not in data:
            return "TEST123"
        return self._bounded_serial(data.get("test_serial"))

    def _send_static_asset(
        self,
        filename: str,
        content_type: str,
        content_encoding: Optional[str] = None,
    ) -> None:
        asset_path = self.STATIC_DIRECTORY / filename
        if not asset_path.is_file():
            self.send_error(404, "Asset Not Found")
            return
        payload = asset_path.read_bytes()
        headers = getattr(self, "headers", {})
        accepted_encodings = headers.get("Accept-Encoding", "")
        if content_encoding == "gzip" and "gzip" not in accepted_encodings.lower():
            payload = gzip.decompress(payload)
            content_encoding = None
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(self)")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "media-src 'self' blob:; "
            "connect-src 'self'",
        )

    def _direct_client_ip(self) -> str:
        client_address = getattr(self, "client_address", ("127.0.0.1", 0))
        return str(client_address[0])

    @staticmethod
    def _is_loopback_ip(value: str) -> bool:
        try:
            return ipaddress.ip_address(value).is_loopback
        except ValueError:
            return False

    def _effective_client_ip(self) -> str:
        direct_ip = self._direct_client_ip()
        if self._is_loopback_ip(direct_ip):
            headers = getattr(self, "headers", {})
            forwarded = headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        return direct_ip

    def _is_remote_client(self) -> bool:
        direct_ip = self._direct_client_ip()
        headers = getattr(self, "headers", {})
        if self._is_loopback_ip(direct_ip) and (
            headers.get("X-Forwarded-For")
            or headers.get("X-Forwarded-Proto")
        ):
            return True
        return not self._is_loopback_ip(self._effective_client_ip())

    def _remote_request_is_rate_limited(self) -> bool:
        if not self._is_remote_client():
            return False
        now = time.monotonic()
        client_ip = self._effective_client_ip()
        cutoff = now - self.REMOTE_RATE_LIMIT_WINDOW_SECONDS
        with self._rate_limit_lock:
            for tracked_ip, tracked_timestamps in list(
                self._remote_request_times.items()
            ):
                recent_timestamps = [
                    timestamp
                    for timestamp in tracked_timestamps
                    if timestamp > cutoff
                ]
                if recent_timestamps:
                    self._remote_request_times[tracked_ip] = recent_timestamps
                else:
                    self._remote_request_times.pop(tracked_ip, None)

            if (
                client_ip not in self._remote_request_times
                and len(self._remote_request_times)
                >= self.MAX_TRACKED_REMOTE_CLIENTS
            ):
                least_recent_client = min(
                    self._remote_request_times,
                    key=lambda tracked_ip: self._remote_request_times[
                        tracked_ip
                    ][-1],
                )
                self._remote_request_times.pop(least_recent_client, None)

            timestamps = [
                timestamp
                for timestamp in self._remote_request_times.get(client_ip, [])
            ]
            limited = len(timestamps) >= self.REMOTE_RATE_LIMIT_REQUESTS
            if not limited:
                timestamps.append(now)
            if timestamps:
                self._remote_request_times[client_ip] = timestamps
            else:
                self._remote_request_times.pop(client_ip, None)
            return limited

    def _has_valid_pairing_token(self, candidate: Optional[str]) -> bool:
        expected = self.pairing_token
        return bool(
            expected
            and candidate
            and hmac.compare_digest(candidate, expected)
        )

    def _request_is_authorized(self) -> bool:
        if not self._is_remote_client():
            return True
        headers = getattr(self, "headers", {})
        cookie_header = headers.get("Cookie", "")
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return False
        morsel = cookie.get(self.SESSION_COOKIE_NAME)
        return self._has_valid_pairing_token(morsel.value if morsel else None)

    def _request_is_https(self) -> bool:
        if not self._is_loopback_ip(self._direct_client_ip()):
            return False
        headers = getattr(self, "headers", {})
        forwarded_proto = headers.get("X-Forwarded-Proto", "")
        return forwarded_proto.split(",", 1)[0].strip().lower() == "https"

    def _establish_remote_pairing(self, query: dict) -> bool:
        if not self._is_remote_client():
            return False
        candidate = query.get("pair", [""])[0]
        if not self._has_valid_pairing_token(candidate):
            return False
        if not self._request_is_https():
            self.send_json(
                {
                    "error": (
                        "Phone camera pairing requires HTTPS. "
                        "Restart web mode with --tunnel and scan the new QR code."
                    )
                },
                status=426,
            )
            return True
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            (
                f"{self.SESSION_COOKIE_NAME}={candidate}; "
                "Path=/; HttpOnly; Secure; SameSite=Strict"
            ),
        )
        self._send_security_headers()
        self.end_headers()
        return True

    def _get_printer_status_payload(self) -> dict:
        assert self.engine is not None
        with self.tsc_profile_lock:
            tsc_conn = self.engine.connectors.get("tsc")
            tsc_status = (
                tsc_conn.get_status()
                if isinstance(tsc_conn, TSCPrinterConnector)
                else {"is_configured": False, "is_ready": False, "detected_queues": []}
            )
        return {
            "active_connector": self.engine.active_connector_key,
            "active_connector_name": self.engine.get_active_connector().connector_name,
            "tsc_status": tsc_status,
        }

    def _handle_save_profile(self, data: dict):
        assert self.engine is not None
        try:
            with self.tsc_profile_lock:
                tsc_conn = self.engine.connectors.get("tsc")
                new_profile, file_path = self.profile_service.save(
                    data, tsc_conn, save_profile_to_file
                )
                if isinstance(tsc_conn, TSCPrinterConnector):
                    tsc_conn.set_profile(new_profile)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return

        if data.get("activate_tsc"):
            self.engine.set_active_connector("tsc")

        self.send_json({
            "success": True,
            "message": f"Profile successfully saved to {file_path}",
            "active_connector": self.engine.active_connector_key,
            "profile": self.profile_service.response_values(new_profile),
        })

    def _handle_calibrate(self, data: dict):
        assert self.engine is not None
        tsc_conn = self.engine.connectors.get("tsc")
        if not isinstance(tsc_conn, TSCPrinterConnector):
            self.send_json({"success": False, "error": "TSC MB341 connector is not available."}, status=400)
            return

        try:
            with self.tsc_profile_lock:
                original_profile = tsc_conn.profile
                # Trial values alter only this test and are always restored.
                test_prof = original_profile
                if data:
                    test_prof = self.profile_service.calibration_profile(data, tsc_conn)
                    tsc_conn.set_profile(test_prof)
                try:
                    test_serial = self._bounded_test_serial(data)
                    if test_serial is None:
                        return
                    res = tsc_conn.print_calibration_label(test_serial=test_serial)
                    tspl_str = ""
                    if test_prof.is_configured():
                        tspl_str = TSPLLabelFormatter.format_calibration_label(
                            test_prof, test_serial
                        ).decode("ascii", errors="ignore")
                finally:
                    tsc_conn.set_profile(original_profile)
        except ValueError as exc:
            self.send_json({"success": False, "error": f"Invalid trial parameters: {exc}"}, status=400)
            return

        self.send_json({
            "success": res.success,
            "printer": res.printer_name,
            "job_id": res.job_id,
            "error": res.error_message,
            "tspl": tspl_str,
        })

    def _handle_preview(self, data: dict):
        assert self.engine is not None
        try:
            with self.tsc_profile_lock:
                tsc_conn = self.engine.connectors.get("tsc")
                prof = self.profile_service.adjusted_profile(data, tsc_conn)
                serial = self._bounded_test_serial(data)
                if serial is None:
                    return
                tspl_bytes = TSPLLabelFormatter.format_calibration_label(
                    prof, test_serial=serial
                )
                tspl_text = tspl_bytes.decode("ascii", errors="ignore")
            self.send_json({
                "success": True,
                "tspl": tspl_text,
                **self.profile_service.response_values(prof),
            })
        except Exception:
            self.send_json({"success": False, "error": "Invalid preview parameters"}, status=400)

    def _handle_toggle_printer(self, data: dict):
        assert self.engine is not None
        connector = data.get("connector", "file")
        try:
            self.engine.set_active_connector(connector)
            self.send_json({
                "success": True,
                "active_connector": self.engine.active_connector_key,
                "active_connector_name": self.engine.get_active_connector().connector_name,
            })
        except Exception as exc:
            self.send_json({"success": False, "error": str(exc)}, status=400)

    public_url: Optional[str] = None

    @classmethod
    def get_html_page(cls, port: Optional[int] = None, public_url: Optional[str] = None) -> str:
        actual_port = port or getattr(cls, "server_port", 9191)
        actual_pub_url = public_url or getattr(cls, "public_url", None)
        local_ip = get_local_ip()
        pairing_url = actual_pub_url or f"http://{local_ip}:{actual_port}"
        pairing_token = getattr(cls, "pairing_token", None)
        if pairing_token:
            parsed_pairing_url = urllib.parse.urlsplit(pairing_url)
            pairing_query = urllib.parse.parse_qsl(
                parsed_pairing_url.query, keep_blank_values=True
            )
            pairing_query.append(("pair", pairing_token))
            pairing_url = urllib.parse.urlunsplit(
                parsed_pairing_url._replace(
                    query=urllib.parse.urlencode(pairing_query)
                )
            )
        plugin_css = cls.plugin_manager.get_all_css()
        plugin_tabs = cls.plugin_manager.get_all_tab_buttons()
        plugin_content = cls.plugin_manager.get_all_content_html(
            local_ip, actual_port, pairing_url
        )
        plugin_js = cls.plugin_manager.get_all_javascript()


        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Universal Warranty & TSC MB341 Calibration Hub</title>
    <style>
        :root {{
            --bg: #09090b;
            --card-bg: #18181b;
            --card-hover: #27272a;
            --border: #27272a;
            --accent: #38bdf8;
            --accent-hover: #0284c7;
            --success: #22c55e;
            --success-bg: rgba(34, 197, 94, 0.1);
            --warning: #f59e0b;
            --warning-bg: rgba(245, 158, 11, 0.1);
            --danger: #ef4444;
            --danger-bg: rgba(239, 68, 68, 0.1);
            --text-main: #f4f4f5;
            --text-muted: #a1a1aa;
            --font-heading: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, sans-serif;
            --font-body: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
            --font-mono: ui-monospace, "SF Mono", "Cascadia Code", "JetBrains Mono", Menlo, Consolas, monospace;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html, body {{
            min-height: 100dvh;
            background: var(--bg);
            color: var(--text-main);
            font-family: var(--font-body);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}
        body {{
            padding: 20px 16px 40px;
            max-width: 1400px;
            margin: 0 auto;
        }}
        header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 16px;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }}
        .tab-label-short {{ display: none; }}
        h1 {{
            font-family: var(--font-heading);
            font-size: 1.4rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            display: flex;
            align-items: center;
            gap: 10px;
            color: #ffffff;
        }}
        h3 {{
            font-family: var(--font-heading);
            font-size: 1.1rem;
            font-weight: 600;
            letter-spacing: -0.01em;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .nav-tabs {{
            display: flex;
            gap: 4px;
            background: #121215;
            padding: 4px;
            border-radius: 8px;
            border: 1px solid var(--border);
            overflow-x: auto;
            max-width: 100%;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
        }}
        .nav-tabs::-webkit-scrollbar {{
            display: none;
        }}
        .tab-btn {{
            background: transparent;
            border: 1px solid transparent;
            color: var(--text-muted);
            padding: 8px 16px;
            border-radius: 6px;
            font-family: var(--font-heading);
            font-weight: 600;
            font-size: 0.875rem;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
            flex-shrink: 0;
            transition: none;
        }}
        .tab-btn:hover {{
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.04);
        }}
        .tab-btn.active {{
            background: var(--card-bg);
            color: var(--accent);
            border-color: var(--border);
        }}

        /* Native Mobile App Shell (<768px) */
        @media (max-width: 768px) {{
            body {{
                padding: 8px 0 68px 0;
                margin: 0;
                max-width: 100%;
                min-height: 100dvh;
            }}
            header {{
                height: 0;
                padding: 0;
                margin: 0;
                border: none;
                overflow: visible;
            }}
            h1 {{
                display: none;
            }}
            .tab-label-full {{ display: none; }}
            .tab-label-short {{ display: inline; }}
            .nav-tabs {{
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                z-index: 900;
                background: #18181b;
                border-top: 1px solid var(--border);
                border-radius: 0;
                border-left: none;
                border-right: none;
                border-bottom: none;
                padding: 6px 4px;
                display: flex;
                justify-content: space-around;
                align-items: center;
                gap: 0;
                height: 60px;
            }}
            .tab-btn {{
                flex-direction: column;
                gap: 2px;
                font-size: 0.7rem;
                padding: 4px 6px;
                border-radius: 6px;
                flex: 1;
                text-align: center;
                justify-content: center;
            }}
            .tab-btn .icon-glyph {{
                width: 20px;
                height: 20px;
            }}
            .card {{
                border-radius: 0;
                border-left: none;
                border-right: none;
                padding: 16px;
                margin-bottom: 8px;
            }}
        }}

        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        @media (max-width: 900px) {{
            .grid-2 {{ grid-template-columns: 1fr; }}
        }}
        .badge {{
            padding: 4px 10px;
            border-radius: 6px;
            font-family: var(--font-mono);
            font-size: 0.775rem;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        .badge-success {{ background: var(--success-bg); color: var(--success); border: 1px solid rgba(34, 197, 94, 0.25); }}
        .badge-warning {{ background: var(--warning-bg); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.25); }}
        .badge-danger {{ background: var(--danger-bg); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.25); }}

        .form-group {{ margin-bottom: 16px; }}
        .form-group label {{
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-bottom: 6px;
            font-weight: 500;
        }}
        .form-group label span.val {{
            color: var(--accent);
            font-family: var(--font-mono);
            font-size: 0.9rem;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }}
        input[type="number"], input[type="text"], select {{
            background: #09090b;
            border: 1px solid var(--border);
            color: #fff;
            padding: 10px 14px;
            font-size: 0.9rem;
            font-family: var(--font-mono);
            font-variant-numeric: tabular-nums;
            border-radius: 8px;
            width: 100%;
            outline: none;
            transition: border-color 0.1s ease;
        }}
        input[type="number"]:focus, input[type="text"]:focus, select:focus {{
            border-color: var(--accent);
        }}
        input[type="range"] {{
            width: 100%;
            accent-color: var(--accent);
            height: 5px;
            background: #27272a;
            border-radius: 3px;
            cursor: pointer;
        }}
        .nudge-row {{
            display: flex;
            gap: 6px;
            margin-top: 6px;
            flex-wrap: wrap;
        }}
        .btn-sm {{
            background: #27272a;
            border: 1px solid var(--border);
            color: var(--text-main);
            padding: 4px 10px;
            font-size: 0.775rem;
            font-family: var(--font-body);
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.1s ease;
        }}
        .btn-sm:hover {{
            background: #3f3f46;
            color: #fff;
        }}
        .btn-sm:active {{
            transform: translateY(1px);
        }}

        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            padding: 10px 18px;
            border-radius: 8px;
            font-family: var(--font-heading);
            font-weight: 600;
            font-size: 0.9rem;
            cursor: pointer;
            border: 1px solid transparent;
            transition: background 0.1s ease, transform 0.1s ease;
            user-select: none;
        }}
        .btn:active {{
            transform: translateY(1px);
        }}
        .btn:focus-visible {{
            outline: 2px solid var(--accent);
            outline-offset: 2px;
        }}
        .btn-primary {{
            background: var(--accent);
            color: #09090b;
            font-weight: 700;
        }}
        .btn-primary:hover {{
            background: var(--accent-hover);
            color: #ffffff;
        }}
        .btn-secondary {{
            background: #27272a;
            color: var(--text-main);
            border: 1px solid var(--border);
        }}
        .btn-secondary:hover {{
            background: #3f3f46;
        }}
        .btn-outline {{
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-muted);
        }}
        .btn-outline:hover {{
            border-color: var(--accent);
            color: var(--accent);
        }}

        /* Live Label Canvas Preview */
        .preview-container {{
            background: #09090b;
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }}
        .label-stock-box {{
            background: #ffffff;
            color: #000000;
            border: 2px solid #3f3f46;
            border-radius: 4px;
            position: relative;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
            overflow: hidden;
            font-family: var(--font-mono);
            user-select: none;
            transition: width 0.2s, height 0.2s;
        }}
        .label-printable-area {{
            position: absolute;
            top: 2px; bottom: 2px; left: 2px; right: 2px;
            border: 1px dashed rgba(0,0,0,0.25);
            pointer-events: none;
        }}
        .label-text-line {{
            position: absolute;
            white-space: nowrap;
            font-weight: bold;
            line-height: 1;
            transform-origin: top left;
        }}
        .tspl-code-box {{
            background: #09090b;
            color: #38bdf8;
            font-family: var(--font-mono);
            font-size: 0.8rem;
            padding: 12px 14px;
            border-radius: 8px;
            border: 1px solid var(--border);
            max-height: 220px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
            line-height: 1.5;
        }}

        .icon-glyph {{
            display: inline-block;
            vertical-align: -0.15em;
            flex-shrink: 0;
            line-height: 1;
        }}
        .hidden {{ display: none !important; }}
        .progress-shell {{ height: 10px; background: #09090b; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; margin: 12px 0 6px; }}
        .progress-bar {{ width: 0%; height: 100%; background: var(--accent); transition: width 150ms ease; }}
        .toast {{ padding: 12px 16px; border-radius: 8px; font-size: 0.875rem; margin-top: 12px; font-family: var(--font-body); }}
        .toast-success {{ background: var(--success-bg); border: 1px solid rgba(34, 197, 94, 0.25); color: var(--success); }}
        .toast-error {{ background: var(--danger-bg); border: 1px solid rgba(239, 68, 68, 0.25); color: var(--danger); }}
        {plugin_css}
    </style>
</head>
<body>
    <header>
        <h1>
            <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.41 2.41 0 0 0 3.408 0l5.83-5.83a2.41 2.41 0 0 0 0-3.408l-8.704-8.704z"/><circle cx="7.5" cy="7.5" r="1.5" fill="currentColor"/></svg>
            Universal Warranty & Printer Hub
        </h1>
        <div class="nav-tabs">
            <button id="tabScanner" class="tab-btn active" onclick="switchTab('scanner')">
                <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                <span class="tab-label-full">Warranty Scanner</span><span class="tab-label-short">Scanner</span>
            </button>
            {plugin_tabs}
            <button id="tabCalibration" class="tab-btn" onclick="switchTab('calibration')">
                <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 9V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v5"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg>
                <span class="tab-label-full">Printer Calibration (TSC MB341)</span><span class="tab-label-short">Printer</span>
            </button>
        </div>
    </header>


    <!-- SCANNER TAB -->
    <div id="scannerSection">
        <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <h3>Point Scanner & Click Trigger</h3>
                <span id="activeDriverBadge" class="badge badge-warning">Active Driver: Virtual File</span>
            </div>
            <input type="text" id="barcodeInput" placeholder="Scan Barcode (Auto-submits instantly)..." autofocus autocomplete="off">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px;">
                <label style="color:var(--text-muted); font-size:0.9rem; cursor:pointer;">
                    <input type="checkbox" id="hardwarePrintToggle"> Print to active output driver on lookup
                </label>
                <a href="/api/export" target="_blank" style="color:var(--accent); font-size:0.85rem; text-decoration:none; font-weight:600; display:inline-flex; align-items:center; gap:4px;">
                    <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Export Audit CSV
                </a>
            </div>
        </div>

        <div id="result" class="card">
            <em>Ready to scan. Point scanner at barcode...</em>
        </div>
    </div>

    <!-- CALIBRATION TAB -->
    <div id="calibrationSection" class="hidden">
        <!-- Status Header Card -->
        <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
                <div>
                    <h3 style="display:flex; align-items:center; gap:8px;">
                        TSC MB341 Hardware Readiness
                        <span id="cupsStatusBadge" class="badge badge-warning">Checking...</span>
                    </h3>
                    <p style="color:var(--text-muted); font-size:0.85rem; margin-top:4px;">
                        Queue: <strong id="statusQueue" style="color:#fff;">TSC_MB341</strong> |
                        URI: <strong id="statusUri" style="color:#fff;">usb://TSC/MB341?serial=000001</strong> |
                        Res: <strong id="statusDpi" style="color:#fff;">300 dpi</strong>
                    </p>
                </div>
                <div style="display:flex; gap:10px; align-items:center;">
                    <span style="font-size:0.85rem; color:var(--text-muted);">Connector:</span>
                    <button id="btnToggleDriver" class="btn btn-outline" onclick="toggleActiveDriver()">
                        Switch to Physical TSC Printer
                    </button>
                </div>
            </div>
        </div>

        <div class="grid-2">
            <!-- Left Column: Controls -->
            <div class="card">
                <h3 style="margin-bottom:16px; color:var(--accent);">
                    <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/><path d="M20 11V3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>
                    Label Stock & Alignment Calibration
                </h3>

                <!-- Stock Dimensions -->
                <div style="background:#09090b; padding:12px; border-radius:8px; margin-bottom:16px; border:1px solid var(--border);">
                    <div style="font-weight:700; font-size:0.85rem; margin-bottom:10px; color:var(--text-muted);">Loaded Stock Dimensions</div>
                    <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px;">
                        <div class="form-group" style="margin:0;">
                            <label>Width (mm) <span class="val" id="lblWidth">76.2</span></label>
                            <input type="number" id="inpWidth" value="76.2" step="0.1" min="10" max="150" oninput="updatePreview()">
                        </div>
                        <div class="form-group" style="margin:0;">
                            <label>Height (mm) <span class="val" id="lblHeight">25.4</span></label>
                            <input type="number" id="inpHeight" value="25.4" step="0.1" min="10" max="200" oninput="updatePreview()">
                        </div>
                        <div class="form-group" style="margin:0;">
                            <label>Gap (mm) <span class="val" id="lblGap">3.0</span></label>
                            <input type="number" id="inpGap" value="3.0" step="0.1" min="0" max="10" oninput="updatePreview()">
                        </div>
                    </div>
                </div>

                <!-- Darkness & Speed -->
                <div class="form-group">
                    <label>Print Darkness / Density (0 - 15) <span class="val" id="lblDarkness">10</span></label>
                    <input type="range" id="rngDarkness" min="0" max="15" value="10" oninput="syncVal('Darkness'); updatePreview()">
                    <div class="nudge-row">
                        <button class="btn-sm" onclick="setVal('Darkness', 7)">7 (Light)</button>
                        <button class="btn-sm" onclick="setVal('Darkness', 10)">10 (Recommended)</button>
                        <button class="btn-sm" onclick="setVal('Darkness', 12)">12 (Dark)</button>
                    </div>
                </div>

                <div class="form-group">
                    <label>Print Speed (20 - 90 mm/s) <span class="val" id="lblSpeed">50</span></label>
                    <input type="range" id="rngSpeed" min="20" max="90" step="5" value="50" oninput="syncVal('Speed'); updatePreview()">
                </div>

                <!-- Offsets -->
                <div class="form-group">
                    <label>Horizontal Offset X (mm) <span class="val" id="lblOffsetX">2.8</span></label>
                    <input type="range" id="rngOffsetX" min="0" max="20" step="0.1" value="2.8" oninput="syncVal('OffsetX'); updatePreview()">
                    <div class="nudge-row">
                        <button class="btn-sm" onclick="nudgeVal('OffsetX', -1.0)">-1.0mm</button>
                        <button class="btn-sm" onclick="nudgeVal('OffsetX', -0.5)">-0.5mm</button>
                        <button class="btn-sm" onclick="nudgeVal('OffsetX', 0.5)">+0.5mm</button>
                        <button class="btn-sm" onclick="nudgeVal('OffsetX', 1.0)">+1.0mm</button>
                    </div>
                </div>

                <div class="form-group">
                    <label>Vertical Shift Y (mm, -25.4 to 25.4) <span class="val" id="lblShiftY">-5.0</span></label>
                    <input type="range" id="rngShiftY" min="-25.4" max="25.4" step="0.5" value="-5.0" oninput="syncVal('ShiftY'); updatePreview()">
                    <div class="nudge-row">
                        <button class="btn-sm" onclick="nudgeVal('ShiftY', -2.0)">-2.0mm</button>
                        <button class="btn-sm" onclick="nudgeVal('ShiftY', -1.0)">-1.0mm</button>
                        <button class="btn-sm" onclick="nudgeVal('ShiftY', -0.5)">-0.5mm</button>
                        <button class="btn-sm" onclick="nudgeVal('ShiftY', 0.5)">+0.5mm</button>
                        <button class="btn-sm" onclick="nudgeVal('ShiftY', 1.0)">+1.0mm</button>
                        <button class="btn-sm" onclick="nudgeVal('ShiftY', 2.0)">+2.0mm</button>
                    </div>
                </div>

                <div style="margin-top:20px; display:flex; gap:10px; flex-wrap:wrap;">
                    <button class="btn btn-outline" style="font-size:0.85rem;" onclick="loadLoadedHardwarePreset()">
                        <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
                        Load 3" × 1" Trial Media Settings
                    </button>
                </div>
            </div>

            <!-- Right Column: Visual Preview & TSPL -->
            <div class="card">
                <h3 style="margin-bottom:16px; color:var(--accent);">
                    <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                    On-Screen Visualizer & TSPL Output
                </h3>

                <div class="preview-container" style="margin-bottom:16px;">
                    <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:8px; display:inline-flex; align-items:center; gap:4px;">
                        Feed Direction
                        <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>
                        (Width: <span id="prevW">76.2</span>mm × Height: <span id="prevH">25.4</span>mm)
                    </div>
                    <div id="labelBox" class="label-stock-box" style="width: 360px; height: 120px;">
                        <div class="label-printable-area"></div>
                        <div id="line1" class="label-text-line" style="top: 8px; left: 10px; font-size: 11px;">PROFILE: MB341 @ 300 dpi</div>
                        <div id="line2" class="label-text-line" style="top: 26px; left: 10px; font-size: 9px; color:#333;">SIZE: 76.2mm x 25.4mm GAP: 3.0mm</div>
                        <div id="line3" class="label-text-line" style="top: 44px; left: 10px; font-size: 9px; color:#333;">DARK: 10 SPEED: 50 OFF: 2.8 SHIFT: -5.0</div>
                        <div id="line4" class="label-text-line" style="top: 62px; left: 10px; font-size: 9px; color:#0284c7;">TEST S/N: TEST123 - CALIBRATION OK</div>
                    </div>
                    <div style="font-size:0.75rem; color:var(--text-muted); margin-top:8px;">
                        Gap: <span id="prevGap">3.0</span>mm | Shift Y: <span id="prevShift"> -5.0</span>mm
                    </div>
                </div>

                <div style="font-weight:600; font-size:0.85rem; margin-bottom:6px; color:var(--text-muted);">Generated Raw TSPL Commands:</div>
                <div id="tsplCodeBox" class="tspl-code-box">SIZE 76.2 mm,25.4 mm...</div>

                <div style="margin-top:20px; display:flex; gap:12px; flex-wrap:wrap;">
                    <button class="btn btn-primary" onclick="printTestLabel()">
                        <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 9V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v5"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg>
                        Print 1 Test Label
                    </button>
                    <button class="btn btn-secondary" onclick="saveWorkingProfile()">
                        <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                        Save Profile to File
                    </button>
                </div>

                <div id="calibrationToast" class="toast hidden"></div>
            </div>
        </div>
    </div>

    <!-- REGISTERED PLUGINS CONTENT -->
    {plugin_content}

    <script>
        const input = document.getElementById('barcodeInput');
        const printToggle = document.getElementById('hardwarePrintToggle');
        const result = document.getElementById('result');
        let scanTimer = null;
        let isProcessing = false;
        let currentStatus = null;

        function escapeHtml(value) {{
            const node = document.createElement('div');
            node.textContent = String(value ?? '');
            return node.innerHTML;
        }}

        function switchTab(tab) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('#scannerSection, #calibrationSection, .plugin-section').forEach(s => s.classList.add('hidden'));

            let targetBtn = document.getElementById('tab_' + tab);
            if (!targetBtn) {{
                if (tab === 'scanner') targetBtn = document.getElementById('tabScanner');
                else if (tab === 'calibration') targetBtn = document.getElementById('tabCalibration');
            }}

            let targetSec = document.getElementById(tab + 'Section');
            if (!targetSec && tab === 'scanner') targetSec = document.getElementById('scannerSection');
            if (!targetSec && tab === 'calibration') targetSec = document.getElementById('calibrationSection');

            if (targetBtn) targetBtn.classList.add('active');
            if (targetSec) targetSec.classList.remove('hidden');

            if (tab === 'scanner') {{
                setTimeout(() => input && input.focus(), 10);
            }} else if (tab === 'calibration') {{
                fetchProfileStatus();
                updatePreview();
            }}
        }}


        async function fetchProfileStatus() {{
            try {{
                const res = await fetch('/api/profile');
                const data = await res.json();
                currentStatus = data;

                const activeKey = data.active_connector;
                const badge = document.getElementById('activeDriverBadge');
                const toggleBtn = document.getElementById('btnToggleDriver');
                if (activeKey === 'tsc') {{
                    badge.className = 'badge badge-success';
                    badge.textContent = 'Active Driver: TSC MB341 Printer';
                    toggleBtn.textContent = 'Switch to Virtual File Output';
                }} else {{
                    badge.className = 'badge badge-warning';
                    badge.textContent = 'Active Driver: Virtual File (Screen Only)';
                    toggleBtn.textContent = 'Switch to Physical TSC Printer';
                }}

                const tsc = data.tsc_status || {{}};
                const cupsBadge = document.getElementById('cupsStatusBadge');
                if (tsc.is_ready) {{
                    cupsBadge.className = 'badge badge-success';
                    cupsBadge.textContent = 'IDLE & ACCEPTING JOBS';
                }} else if (tsc.is_configured) {{
                    cupsBadge.className = 'badge badge-warning';
                    cupsBadge.textContent = 'QUEUE NOT DETECTED';
                }} else {{
                    cupsBadge.className = 'badge badge-danger';
                    cupsBadge.textContent = 'PROFILE UNCONFIGURED';
                }}

                document.getElementById('statusQueue').textContent = tsc.queue_name || 'TSC_MB341';
                document.getElementById('statusUri').textContent = 'usb://TSC/MB341?serial=000001';
                document.getElementById('statusDpi').textContent = (tsc.dpi || 300) + ' dpi';

                if (tsc.profile && tsc.profile.width_mm) {{
                    document.getElementById('inpWidth').value = tsc.profile.width_mm;
                    document.getElementById('inpHeight').value = tsc.profile.height_mm;
                    document.getElementById('inpGap').value = tsc.profile.gap_mm;
                    document.getElementById('rngDarkness').value = tsc.profile.darkness;
                    document.getElementById('rngSpeed').value = tsc.profile.speed;
                    document.getElementById('rngOffsetX').value = tsc.profile.offset_x_mm;
                    document.getElementById('rngShiftY').value = tsc.profile.shift_y_mm;
                    syncAllLabels();
                }}
                updatePreview();
            }} catch(err) {{
                console.error("Error fetching status:", err);
            }}
        }}

        async function toggleActiveDriver() {{
            const target = currentStatus && currentStatus.active_connector === 'tsc' ? 'file' : 'tsc';
            try {{
                const res = await fetch('/api/printer/toggle', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ connector: target }})
                }});
                const data = await res.json();
                fetchProfileStatus();
            }} catch(err) {{
                alert("Failed to toggle driver: " + err);
            }}
        }}

        function syncVal(name) {{
            const rng = document.getElementById('rng' + name);
            const lbl = document.getElementById('lbl' + name);
            if (rng && lbl) lbl.textContent = parseFloat(rng.value).toFixed(1).replace('.0', '');
        }}

        function syncAllLabels() {{
            syncVal('Darkness');
            syncVal('Speed');
            syncVal('OffsetX');
            syncVal('ShiftY');
            document.getElementById('lblWidth').textContent = document.getElementById('inpWidth').value;
            document.getElementById('lblHeight').textContent = document.getElementById('inpHeight').value;
            document.getElementById('lblGap').textContent = document.getElementById('inpGap').value;
        }}

        function setVal(name, val) {{
            const rng = document.getElementById('rng' + name);
            if (rng) {{ rng.value = val; syncVal(name); updatePreview(); }}
        }}

        function nudgeVal(name, delta) {{
            const rng = document.getElementById('rng' + name);
            if (rng) {{
                const cur = parseFloat(rng.value) || 0;
                rng.value = (cur + delta).toFixed(1);
                syncVal(name);
                updatePreview();
            }}
        }}

        function loadLoadedHardwarePreset() {{
            document.getElementById('inpWidth').value = 76.2;
            document.getElementById('inpHeight').value = 25.4;
            document.getElementById('inpGap').value = 3.0;
            setVal('Darkness', 10);
            setVal('Speed', 50);
            setVal('OffsetX', 2.8);
            setVal('ShiftY', -5.0);
            updatePreview();
        }}

        function updatePreview() {{
            syncAllLabels();
            const w = parseFloat(document.getElementById('inpWidth').value) || 76.2;
            const h = parseFloat(document.getElementById('inpHeight').value) || 25.4;
            const g = parseFloat(document.getElementById('inpGap').value) || 3.0;
            const d = parseInt(document.getElementById('rngDarkness').value) || 10;
            const s = parseInt(document.getElementById('rngSpeed').value) || 50;
            const ox = parseFloat(document.getElementById('rngOffsetX').value) || 0;
            const sy = parseFloat(document.getElementById('rngShiftY').value) || 0;

            document.getElementById('prevW').textContent = w;
            document.getElementById('prevH').textContent = h;
            document.getElementById('prevGap').textContent = g;
            document.getElementById('prevShift').textContent = sy;

            const box = document.getElementById('labelBox');
            const scale = Math.min(420 / w, 160 / h);
            box.style.width = Math.round(w * scale) + 'px';
            box.style.height = Math.round(h * scale) + 'px';

            // Vertical shift effect visualization on text lines inside preview box
            const dotsDpi = 300;
            const shiftPixels = (sy * scale);
            const offsetPixels = (ox * scale);

            const l1 = document.getElementById('line1');
            const l2 = document.getElementById('line2');
            const l3 = document.getElementById('line3');
            const l4 = document.getElementById('line4');

            l1.style.top = Math.max(2, Math.round((24 * h / 25.4) * scale / 3 + shiftPixels)) + 'px';
            l1.style.left = Math.round(10 + offsetPixels) + 'px';

            l2.style.top = Math.max(2, Math.round((56 * h / 25.4) * scale / 3 + shiftPixels)) + 'px';
            l2.style.left = Math.round(10 + offsetPixels) + 'px';

            l3.style.top = Math.max(2, Math.round((86 * h / 25.4) * scale / 3 + shiftPixels)) + 'px';
            l3.style.left = Math.round(10 + offsetPixels) + 'px';
            l3.textContent = `DARK: ${{d}} SPEED: ${{s}} OFF: ${{ox}}mm SHIFT: ${{sy}}mm`;

            l4.style.top = Math.max(2, Math.round((114 * h / 25.4) * scale / 3 + shiftPixels)) + 'px';
            l4.style.left = Math.round(10 + offsetPixels) + 'px';

            // Fetch live TSPL text payload from backend
            fetch('/api/preview', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ width_mm: w, height_mm: h, gap_mm: g, darkness: d, speed: s, offset_x_mm: ox, shift_y_mm: sy }})
            }})
            .then(r => r.json())
            .then(data => {{
                if (data.tspl) document.getElementById('tsplCodeBox').textContent = data.tspl;
            }}).catch(() => {{}});
        }}

        async function saveWorkingProfile() {{
            const toast = document.getElementById('calibrationToast');
            toast.className = 'toast hidden';
            const bodyData = {{
                width_mm: parseFloat(document.getElementById('inpWidth').value),
                height_mm: parseFloat(document.getElementById('inpHeight').value),
                gap_mm: parseFloat(document.getElementById('inpGap').value),
                darkness: parseInt(document.getElementById('rngDarkness').value),
                speed: parseInt(document.getElementById('rngSpeed').value),
                offset_x_mm: parseFloat(document.getElementById('rngOffsetX').value),
                shift_y_mm: parseFloat(document.getElementById('rngShiftY').value),
                activate_tsc: true
            }};

            try {{
                const res = await fetch('/api/profile', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(bodyData)
                }});
                const data = await res.json();
                if (data.success) {{
                    toast.className = 'toast toast-success';
                    toast.textContent = '✓ ' + data.message;
                    fetchProfileStatus();
                }} else {{
                    toast.className = 'toast toast-error';
                    toast.textContent = '❌ Save failed: ' + (data.error || 'Unknown error');
                }}
            }} catch(err) {{
                toast.className = 'toast toast-error';
                toast.textContent = '❌ Connection error: ' + err;
            }}
        }}

        async function printTestLabel() {{
            const toast = document.getElementById('calibrationToast');
            toast.className = 'toast toast-success';
            toast.textContent = '⏳ Submitting 1 test label job to TSC MB341 hardware...';

            const bodyData = {{
                width_mm: parseFloat(document.getElementById('inpWidth').value),
                height_mm: parseFloat(document.getElementById('inpHeight').value),
                gap_mm: parseFloat(document.getElementById('inpGap').value),
                darkness: parseInt(document.getElementById('rngDarkness').value),
                speed: parseInt(document.getElementById('rngSpeed').value),
                offset_x_mm: parseFloat(document.getElementById('rngOffsetX').value),
                shift_y_mm: parseFloat(document.getElementById('rngShiftY').value),
                test_serial: "TEST123"
            }};

            try {{
                const res = await fetch('/api/calibrate', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(bodyData)
                }});
                const data = await res.json();
                if (data.success) {{
                    toast.className = 'toast toast-success';
                    toast.textContent = `✓ Calibration test label printed successfully! Printer: ${{data.printer}} | Job ID: ${{data.job_id || 'Submitted'}}`;
                }} else {{
                    toast.className = 'toast toast-error';
                    toast.textContent = `❌ Calibration print blocked: ${{data.error || 'CUPS error'}}`;
                }}
            }} catch(err) {{
                toast.className = 'toast toast-error';
                toast.textContent = '❌ Error submitting test print: ' + err;
            }}
        }}

        document.addEventListener('click', (e) => {{
            if (document.getElementById('scannerSection').classList.contains('hidden')) return;
            if (e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON') input.focus();
        }});

        function triggerSubmit() {{
            const val = input.value.trim();
            if (!val || isProcessing) return;
            isProcessing = true;
            input.value = '';
            processBarcode(val);
        }}

        input.addEventListener('keypress', (e) => {{
            if (e.key === 'Enter') {{
                if (scanTimer) clearTimeout(scanTimer);
                triggerSubmit();
            }}
        }});

        input.addEventListener('input', () => {{
            if (scanTimer) clearTimeout(scanTimer);
            const val = input.value.trim();
            if ([7, 8, 10, 11, 12].includes(val.length)) {{
                scanTimer = setTimeout(triggerSubmit, 60);
            }} else if (val.length >= 5) {{
                scanTimer = setTimeout(triggerSubmit, 150);
            }}
        }});

        async function processBarcode(val) {{
            const isEEScan = /^\\s*558[\\s-]*EE[\\s-]*[0-9]{{1,20}}\\s*$/i.test(val);
            try {{
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ctx.createOscillator();
                osc.connect(ctx.destination);
                osc.frequency.value = 900;
                osc.start();
                osc.stop(ctx.currentTime + 0.1);
            }} catch(err) {{}}

            const started = performance.now();
            result.innerHTML =
                (isEEScan ? 'Preparing EE label for ' : 'Querying warranty for ') +
                '<strong style="color:#38bdf8;">' + escapeHtml(val) + '</strong>' +
                '<div class="progress-shell"><div id="lookupProgress" class="progress-bar"></div></div>' +
                '<div id="lookupProgressMeta" class="progress-meta">' +
                (isEEScan ? 'Validating internal EE number…' : 'Starting preloaded browser… 0.0s') +
                '</div>';
            const progressBar = document.getElementById('lookupProgress');
            const progressMeta = document.getElementById('lookupProgressMeta');
            let displayedProgress = 8;
            progressBar.style.width = displayedProgress + '%';
            const progressTimer = setInterval(() => {{
                const elapsed = (performance.now() - started) / 1000;
                displayedProgress = Math.min(92, displayedProgress + (displayedProgress < 60 ? 5 : 1));
                progressBar.style.width = displayedProgress + '%';
                progressMeta.textContent = isEEScan
                    ? 'Preparing internal EE label…'
                    : 'Waiting for vendor portal… ' + elapsed.toFixed(1) + 's';
            }}, 250);

            try {{
                const shouldPrint = printToggle.checked;
                const res = await fetch('/api/scan?serial=' + encodeURIComponent(val) + '&print=' + shouldPrint);
                const data = await res.json();
                clearInterval(progressTimer);
                progressBar.style.width = '100%';
                const statusClass = ['Active', 'Expired', 'Coverage'].includes(
                    String(data.status).split(' ')[0]
                ) ? String(data.status).split(' ')[0] : 'Expired';
                let saveMessage = 'Label save: Not requested';
                if (shouldPrint && data.print_result) {{
                    saveMessage = data.print_result.success
                        ? 'Label job sent: ' + escapeHtml(data.print_result.printer || '') + (data.print_result.output_path ? ' (' + escapeHtml(data.print_result.output_path) + ')' : '')
                        : 'Label blocked: ' + escapeHtml(data.print_result.error || 'Unknown error');
                }}

                if (data.mode === 'ee') {{
                    result.innerHTML = `
                        <h2>INTERNAL EE LABEL</h2>
                        <p style="font-family:monospace; font-size:3rem; font-weight:800; letter-spacing:0.08em; margin:1.25rem 0;">${{escapeHtml(data.ee_number)}}</p>
                        <div class="badge badge-success">READY</div>
                        <p style="color:#94a3b8; font-size:0.85rem;">${{saveMessage}}</p>
                    `;
                    return;
                }}

                result.innerHTML = `
                    <h2>${{escapeHtml(data.vendor)}} - ${{escapeHtml(data.model)}}</h2>
                    <p>Serial Tag: <strong style="font-family:monospace; font-size:1.2rem;">${{escapeHtml(data.serial)}}</strong></p>
                    <div class="badge ${{statusClass === 'Active' ? 'badge-success' : 'badge-danger'}}">${{escapeHtml(data.status)}}${{data.status === 'Lookup Failed' ? '' : ' WARRANTY'}}</div>
                    <p>Coverage Start: ${{escapeHtml(data.ship_date)}}</p>
                    <p>Expiration Date: <span style="color:#ef4444; font-weight:bold;">${{escapeHtml(data.expiration_date)}}</span></p>
                    <p>Source: <strong>${{escapeHtml(data.source_confidence)}}</strong></p>
                    <p style="color:#38bdf8; font-family:monospace;">Lookup completed in ${{escapeHtml(data.lookup_ms)}} ms</p>
                    ${{data.lookup_error ? `<p style="color:#ef4444;">${{escapeHtml(data.lookup_error)}}</p>` : ''}}
                    <p style="color:#94a3b8; font-size:0.85rem;">${{saveMessage}}</p>
                `;
            }} catch(err) {{
                clearInterval(progressTimer);
                result.innerHTML = '<span style="color:#ef4444;">Error processing barcode lookup.</span>';
            }} finally {{
                isProcessing = false;
                setTimeout(() => input.focus(), 10);
            }}
        }}

        fetchProfileStatus();
    </script>
    {plugin_js}
</body>
</html>"""


def run_web_mode(port=9191, public_url: Optional[str] = None):
    engine = WarrantyEngine()
    engine.start()
    WebInterfaceHandler.engine = engine
    WebInterfaceHandler.server_port = port
    WebInterfaceHandler.public_url = public_url
    WebInterfaceHandler.pairing_token = secrets.token_urlsafe(24)
    local_ip = get_local_ip()
    server_address = ('', port)
    httpd = ConcurrentWebServer(server_address, WebInterfaceHandler)

    print(f"\n[WEB SERVER STARTED] Universal Warranty Dashboard running at:")
    print(f" - Local:           http://localhost:{port}")
    if public_url:
        print(f" - Public Tunnel:   {public_url}")
    else:
        print(f" - Phone / Network: http://{local_ip}:{port}\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[WEB SERVER STOPPED]")
    finally:
        engine.stop()
