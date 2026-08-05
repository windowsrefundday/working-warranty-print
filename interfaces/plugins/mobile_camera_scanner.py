import socket
from typing import Dict, Any, Optional, Tuple
from interfaces.plugins.base import BaseWebPlugin
from interfaces.plugins.qr_generator import PureQRCode

def get_local_ip() -> str:
    """Detect the local primary network IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class MobileCameraScannerPlugin(BaseWebPlugin):
    """
    Modular plugin for smartphone camera barcode scanning, automatic warranty lookup,
    and direct label printing with QR code pairing for desktop-to-mobile setup.
    """

    @property
    def plugin_id(self) -> str:
        return "mobile_camera_scanner"

    @property
    def name(self) -> str:
        return "Phone Camera Scanner"

    @property
    def icon(self) -> str:
        return '<svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>'

    @property
    def short_name(self) -> str:
        return "Camera"

    def get_css(self) -> str:
        return """
        .mobile-scanner-card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            position: relative;
        }
        .mobile-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .mobile-header h2 {
            font-family: var(--font-heading);
            font-size: 1.15rem;
            font-weight: 700;
            letter-spacing: -0.015em;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .gear-btn {
            background: #27272a;
            border: 1px solid var(--border);
            color: var(--text-main);
            width: 34px;
            height: 34px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: none;
        }
        .gear-btn:hover {
            border-color: var(--accent);
            color: var(--accent);
        }

        .viewfinder-container {
            position: relative;
            width: 100%;
            max-width: 640px;
            margin: 0 auto 14px auto;
            border-radius: 12px;
            overflow: hidden;
            background: #000;
            aspect-ratio: 4 / 3;
            border: 1px solid var(--border);
        }
        #mobileCameraVideo {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }
        .reticle-box {
            position: absolute;
            top: 20%;
            left: 15%;
            width: 70%;
            height: 60%;
            border: 2px solid var(--accent);
            border-radius: 12px;
            pointer-events: none;
            box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.45);
        }
        .reticle-box.scan-success {
            border-color: var(--success) !important;
            box-shadow: 0 0 0 9999px rgba(34, 197, 94, 0.15) !important;
        }
        .reticle-corner {
            position: absolute;
            width: 16px;
            height: 16px;
            border-color: var(--accent);
            border-style: solid;
        }
        .reticle-corner.top-left { top: -2px; left: -2px; border-width: 3px 0 0 3px; }
        .reticle-corner.top-right { top: -2px; right: -2px; border-width: 3px 3px 0 0; }
        .reticle-corner.bottom-left { bottom: -2px; left: -2px; border-width: 0 0 3px 3px; }
        .reticle-corner.bottom-right { bottom: -2px; right: -2px; border-width: 0 3px 3px 0; }

        .overlay-msg {
            position: absolute;
            top: 12px;
            left: 12px;
            right: 12px;
            max-width: calc(100% - 64px);
            z-index: 870;
            background: rgba(9, 9, 11, 0.85);
            color: var(--text-main);
            font-family: var(--font-heading);
            font-size: 0.825rem;
            font-weight: 600;
            padding: 6px 12px;
            border-radius: 8px;
            border: 1px solid var(--border);
            pointer-events: none;
        }

        .camera-controls {
            display: flex;
            gap: 8px;
            justify-content: center;
            flex-wrap: wrap;
            margin-bottom: 14px;
        }

        /* Mobile App Shell: Full-Viewport Camera (<768px) */
        @media (max-width: 768px) {
            .mobile-scanner-card {
                padding: 0;
                border: none;
                background: transparent;
            }
            .mobile-header {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                z-index: 860;
                background: rgba(9, 9, 11, 0.65);
                padding: 10px 16px;
                margin: 0;
                border: none;
            }
            .mobile-header h2 {
                display: none;
            }
            .overlay-msg {
                position: fixed;
                top: 48px;
                left: 12px;
                right: 12px;
                max-width: calc(100% - 24px);
                z-index: 870;
            }
            .viewfinder-container {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 60px;
                width: 100%;
                height: auto;
                max-width: 100%;
                border-radius: 0;
                border: none;
                margin: 0;
                aspect-ratio: unset;
                z-index: 850;
            }
            .camera-controls {
                position: fixed;
                bottom: 68px;
                left: 0;
                right: 0;
                z-index: 860;
                background: rgba(9, 9, 11, 0.65);
                padding: 10px 16px;
                margin: 0;
                justify-content: center;
            }
        }

        /* Settings Gear Modal */
        .settings-modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.85);
            z-index: 1050;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 16px;
            transition: none !important;
            animation: none !important;
        }
        .settings-modal-overlay.hidden { display: none !important; }
        .settings-modal-card {
            background: #18181b;
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 20px;
            max-width: 500px;
            width: 100%;
            max-height: 85vh;
            overflow-y: auto;
        }

        /* Google Lens / Pokédex Instant Bottom Card Popup */
        .bottom-sheet {
            position: fixed;
            bottom: 68px;
            left: 12px;
            right: 12px;
            max-width: 600px;
            margin: 0 auto;
            background: #18181b;
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 14px 18px 18px;
            z-index: 950;
            box-shadow: 0 -8px 30px rgba(0, 0, 0, 0.95);
            transition: none !important;
            animation: none !important;
        }
        .bottom-sheet.hidden { display: none !important; }
        .sheet-handle {
            width: 36px;
            height: 4px;
            background: #3f3f46;
            border-radius: 2px;
            margin: 0 auto 10px auto;
        }
        .sheet-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .sheet-close-btn {
            background: #27272a;
            border: 1px solid var(--border);
            color: var(--text-muted);
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.9rem;
            cursor: pointer;
        }
        .sheet-close-btn:hover { color: #fff; background: #3f3f46; }
        .sheet-title {
            font-family: var(--font-mono);
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--accent);
            margin-bottom: 2px;
        }
        .sheet-subtitle {
            font-size: 0.9rem;
            font-weight: 600;
            color: #ffffff;
            margin-bottom: 8px;
        }
        .sheet-details-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            background: #09090b;
            padding: 8px 12px;
            border-radius: 8px;
            border: 1px solid var(--border);
            font-size: 0.8rem;
        }
        /* Desktop Settings Header (Top of page on >768px) */
        .desktop-settings-header {
            margin-bottom: 16px;
        }
        @media (min-width: 769px) {
            .gear-btn {
                display: none !important;
            }
            .settings-modal-overlay {
                display: none !important;
            }
        }
        @media (max-width: 768px) {
            .desktop-settings-header {
                display: none !important;
            }
        }
        """

    def get_content_html(self, host: str, port: int, public_url: Optional[str] = None) -> str:
        local_ip = get_local_ip()
        pairing_url = public_url if public_url else f"http://{local_ip}:{port}"
        qr_svg = PureQRCode(pairing_url).to_svg(110)

        return f"""
        <div class="mobile-scanner-card">
            <div class="mobile-header">
                <h2>
                    <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
                    Google Lens Scanner
                </h2>
                <div style="display:flex; gap:8px; align-items:center;">
                    <span id="cameraStatusBadge" class="badge badge-warning">Standby</span>
                    <button class="gear-btn" onclick="window.mobileScannerPlugin.openSettingsModal()" title="Settings & QR Pairing">
                        <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                    </button>
                </div>
            </div>

            <!-- Desktop Settings Header (Rendered on Desktop Top of Page) -->
            <div class="desktop-settings-header">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                    <!-- Pairing Box -->
                    <div style="background:#09090b; border:1px solid var(--border); border-radius:10px; padding:14px; display:flex; align-items:center; justify-content:space-between; gap:16px;">
                        <div>
                            <div style="font-weight:700; color:var(--accent); font-size:0.95rem; margin-bottom:4px; display:flex; align-items:center; gap:6px;">
                                <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></svg>
                                Desktop QR Pairing Link
                            </div>
                            <code style="color:#fff; font-size:0.85rem; word-break:break-all;">{pairing_url}</code>
                            <div style="font-size:0.8rem; color:var(--text-muted); margin-top:4px;">Scan with phone camera to connect</div>
                        </div>
                        <div style="background:#fff; padding:6px; border-radius:8px; min-width:90px; text-align:center;">
                            {qr_svg}
                        </div>
                    </div>

                    <!-- Manual Input & Toggles -->
                    <div style="background:#09090b; border:1px solid var(--border); border-radius:10px; padding:14px; display:flex; flex-direction:column; justify-content:space-between; gap:10px;">
                        <div>
                            <label for="mobileManualSerial" style="font-weight:700; font-size:0.85rem; display:block; margin-bottom:6px;">Manual Serial Entry</label>
                            <div style="display:flex; gap:8px;">
                                <input id="mobileManualSerial" type="text" autocomplete="off" placeholder="Enter serial..." style="flex:1;">
                                <button class="btn btn-secondary" onclick="window.mobileScannerPlugin.submitManualSerial();">
                                    Lookup
                                </button>
                            </div>
                        </div>
                        <div style="display:flex; gap:16px; align-items:center;">
                            <label class="setting-row" style="margin:0;">
                                <input type="checkbox" id="autoPrintOnScan">
                                <span><strong>Auto-Print on Scan</strong></span>
                            </label>
                            <label class="setting-row" style="margin:0;">
                                <input type="checkbox" id="hapticFeedback" checked>
                                <span><strong>Beep & Haptic Feedback</strong></span>
                            </label>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Full-Screen Hero Camera Viewfinder -->
            <div class="viewfinder-container">
                <video id="mobileCameraVideo" playsinline autoplay muted></video>
                <div id="cameraReticle" class="reticle-box">
                    <div class="reticle-corner top-left"></div>
                    <div class="reticle-corner top-right"></div>
                    <div class="reticle-corner bottom-left"></div>
                    <div class="reticle-corner bottom-right"></div>
                </div>
                <div id="cameraOverlayText" class="overlay-msg">Point camera at serial barcode</div>
            </div>

            <!-- Camera Controls Overlay -->
            <div class="camera-controls">
                <button id="btnToggleCamera" class="btn btn-primary" onclick="window.mobileScannerPlugin.toggleCamera()">
                    <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>
                    Start Camera
                </button>
                <button id="btnFlipCamera" class="btn btn-secondary" onclick="window.mobileScannerPlugin.flipCamera()" disabled>
                    <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6"/><path d="M2.5 22v-6h6"/><path d="M2 11.5a10 10 0 0 1 18.8-4.3L21.5 8"/><path d="M22 12.5a10 10 0 0 1-18.8 4.2L2.5 16"/></svg>
                    Flip
                </button>
                <button id="btnTorch" class="btn btn-outline" onclick="window.mobileScannerPlugin.toggleTorch()" disabled>
                    <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                    Flashlight
                </button>
            </div>

            <!-- Top Settings Gear Modal Overlay (For Mobile Screen View) -->
            <div id="settingsGearModal" class="settings-modal-overlay hidden">
                <div class="settings-modal-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                        <h3 style="margin:0; font-size:1.1rem; display:flex; align-items:center; gap:6px;">
                            <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                            Scanner Settings &amp; QR Pairing
                        </h3>
                        <button class="sheet-close-btn" onclick="window.mobileScannerPlugin.closeSettingsModal()">✕</button>
                    </div>

                    <!-- Pairing Box -->
                    <div style="background:#09090b; border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:14px;">
                        <div style="font-weight:700; color:var(--accent); font-size:0.9rem; margin-bottom:4px;">Desktop QR Pairing Link</div>
                        <code style="color:#fff; font-size:0.85rem;">{pairing_url}</code>
                        <div style="margin-top:8px; display:flex; justify-content:center; background:#fff; padding:6px; border-radius:6px;">
                            {qr_svg}
                        </div>
                    </div>

                    <!-- Manual Input -->
                    <div style="background:#09090b; border:1px solid var(--border); border-radius:8px; padding:12px; margin-bottom:14px;">
                        <label for="mobileManualSerialModal" style="font-weight:700; font-size:0.85rem; display:block; margin-bottom:6px;">Manual Serial Entry</label>
                        <div style="display:flex; gap:8px;">
                            <input id="mobileManualSerialModal" type="text" autocomplete="off" placeholder="Enter serial..." style="flex:1;">
                            <button class="btn btn-secondary" onclick="window.mobileScannerPlugin.submitManualSerial(); window.mobileScannerPlugin.closeSettingsModal();">
                                Lookup
                            </button>
                        </div>
                    </div>

                    <!-- Toggles -->
                    <div style="background:#09090b; border:1px solid var(--border); border-radius:8px; padding:12px; display:flex; flex-direction:column; gap:10px;">
                        <label class="setting-row">
                            <input type="checkbox" id="autoPrintOnScanModal">
                            <span><strong>Auto-Print on Scan</strong></span>
                        </label>
                        <label class="setting-row">
                            <input type="checkbox" id="hapticFeedbackModal" checked>
                            <span><strong>Beep & Haptic Feedback</strong></span>
                        </label>
                    </div>
                </div>
            </div>

            <!-- Instant Pokédex / Google Lens Warranty Popup Card -->
            <div id="warrantyBottomSheet" class="bottom-sheet hidden">
                <div class="sheet-handle"></div>
                <div class="sheet-header">
                    <div style="display:flex; gap:6px; align-items:center;">
                        <span id="sheetVendorBadge" class="badge badge-warning">VENDOR</span>
                        <span id="sheetStatusBadge" class="badge badge-success">VALID WARRANTY</span>
                    </div>
                    <button class="sheet-close-btn" onclick="window.mobileScannerPlugin.closeBottomSheet()">✕</button>
                </div>
                <div class="sheet-body">
                    <div id="sheetSerialNumber" class="sheet-title">SN: LENOVO12345</div>
                    <div id="sheetModelName" class="sheet-subtitle">ThinkPad Laptop</div>
                    <div class="sheet-details-grid">
                        <div><span style="color:var(--text-muted);">Expiration:</span> <br><strong id="sheetEndDate" style="color:#fff;">2027-12-31</strong></div>
                        <div><span style="color:var(--text-muted);">Entitlement:</span> <br><strong id="sheetTier" style="color:#fff;">On-Site Support</strong></div>
                    </div>
                </div>
                <div class="sheet-actions">
                    <button id="btnSheetPrint" class="btn btn-primary btn-full" onclick="window.mobileScannerPlugin.printCurrentSheetLabel()">
                        <svg class="icon-glyph" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 9V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v5"/><rect x="6" y="14" width="12" height="8" rx="1"/></svg>
                        Print 1 Warranty Label
                    </button>
                </div>
            </div>
        </div>
        """

    def get_javascript(self) -> str:
        return """
        <script src="/assets/zxing-browser-0.2.1.min.js"></script>
        <script>
        class MobileCameraScannerPluginController {
            constructor() {
                this.stream = null;
                this.facingMode = 'environment';
                this.isScanning = false;
                this.isProcessingScan = false;
                this.lastScannedSerial = '';
                this.lastScanTime = 0;
                this.currentSheetSerial = '';
                this.torchState = false;
                this.barcodeDetector = null;
                this.zxingReader = null;
                this.zxingCanvas = null;
                this.decoderName = null;
                this.audioCtx = null;
                this.autoPrintEnabled = false;
                this.hapticEnabled = true;
                this.decoderReady = this.initBarcodeDetector();

                document.addEventListener('DOMContentLoaded', () => {
                    document.getElementById('mobileManualSerial')?.addEventListener('keydown', (event) => {
                        if (event.key === 'Enter') {
                            this.submitManualSerial();
                            this.closeSettingsModal();
                        }
                    });
                    document.getElementById('mobileManualSerialModal')?.addEventListener('keydown', (event) => {
                        if (event.key === 'Enter') {
                            this.submitManualSerial();
                            this.closeSettingsModal();
                        }
                    });
                    this.syncTogglePair('autoPrintOnScan', 'autoPrintOnScanModal', 'autoPrintEnabled', false);
                    this.syncTogglePair('hapticFeedback', 'hapticFeedbackModal', 'hapticEnabled', true);
                });
            }

            syncTogglePair(primaryId, secondaryId, stateProperty, defaultValue) {
                const primary = document.getElementById(primaryId);
                const secondary = document.getElementById(secondaryId);
                const initialValue = primary?.checked ?? secondary?.checked ?? defaultValue;
                this[stateProperty] = initialValue;
                if (primary) primary.checked = initialValue;
                if (secondary) secondary.checked = initialValue;

                const update = (source, target) => {
                    this[stateProperty] = !!source.checked;
                    if (target) target.checked = this[stateProperty];
                };
                primary?.addEventListener('change', () => update(primary, secondary));
                secondary?.addEventListener('change', () => update(secondary, primary));
            }

            openSettingsModal() {
                const modal = document.getElementById('settingsGearModal');
                if (modal) modal.classList.remove('hidden');
            }

            closeSettingsModal() {
                const modal = document.getElementById('settingsGearModal');
                if (modal) modal.classList.add('hidden');
            }

            async initBarcodeDetector() {
                if ('BarcodeDetector' in window) {
                    try {
                        const formats = await BarcodeDetector.getSupportedFormats();
                        this.barcodeDetector = new BarcodeDetector({ formats: formats.length > 0 ? formats : ['code_128', 'code_39', 'qr_code', 'ean_13', 'upc_a'] });
                        this.decoderName = 'Native BarcodeDetector';
                        return true;
                    } catch(e) {
                        console.warn('Native barcode detector initialization failed:', e);
                    }
                }

                try {
                    if (window.ZXingBrowser?.BrowserMultiFormatReader) {
                        this.zxingReader = new window.ZXingBrowser.BrowserMultiFormatReader();
                        this.zxingCanvas = document.createElement('canvas');
                        this.decoderName = 'ZXing';
                        return true;
                    }
                } catch(e) {
                    console.error('ZXing initialization failed:', e);
                }

                const badge = document.getElementById('cameraStatusBadge');
                const overlay = document.getElementById('cameraOverlayText');
                if (badge) {
                    badge.textContent = 'Decoder Error';
                    badge.className = 'badge badge-danger';
                }
                if (overlay) {
                    overlay.textContent = 'Barcode decoder failed to load. Reload this page.';
                }
                return false;
            }

            async toggleCamera() {
                if (this.isScanning) {
                    this.stopCamera();
                } else {
                    await this.startCamera();
                }
            }

            async startCamera() {
                const video = document.getElementById('mobileCameraVideo');
                const badge = document.getElementById('cameraStatusBadge');
                const overlay = document.getElementById('cameraOverlayText');
                const toggleBtn = document.getElementById('btnToggleCamera');
                const flipBtn = document.getElementById('btnFlipCamera');

                try {
                    const decoderAvailable = await this.decoderReady;
                    if (!decoderAvailable) {
                        throw new Error('Barcode decoder is unavailable. Reload the page and try again.');
                    }
                    const constraints = {
                        video: {
                            facingMode: { ideal: this.facingMode },
                            width: { ideal: 1280 },
                            height: { ideal: 720 }
                        }
                    };

                    this.stream = await navigator.mediaDevices.getUserMedia(constraints);
                    video.srcObject = this.stream;
                    await video.play();

                    this.isScanning = true;
                    if (toggleBtn) {
                        toggleBtn.textContent = 'Stop Camera';
                        toggleBtn.className = 'btn btn-secondary';
                    }
                    if (flipBtn) flipBtn.disabled = false;
                    if (badge) {
                        badge.textContent = 'Active';
                        badge.className = 'badge badge-success';
                    }
                    if (overlay) overlay.textContent = 'Point camera at serial barcode...';

                    const track = this.stream.getVideoTracks()[0];
                    const capabilities = track.getCapabilities ? track.getCapabilities() : {};
                    const torchBtn = document.getElementById('btnTorch');
                    if (torchBtn) torchBtn.disabled = !capabilities.torch;

                    this.runScanLoop();
                } catch(err) {
                    console.error('Camera access error:', err);
                    if (overlay) overlay.textContent = 'Camera error: ' + (err.message || 'Permission denied');
                    if (badge) {
                        badge.textContent = 'Error';
                        badge.className = 'badge badge-danger';
                    }
                }
            }

            stopCamera() {
                if (this.stream) {
                    this.stream.getTracks().forEach(track => track.stop());
                    this.stream = null;
                }
                this.isScanning = false;
                const video = document.getElementById('mobileCameraVideo');
                if (video) video.srcObject = null;

                const badge = document.getElementById('cameraStatusBadge');
                const overlay = document.getElementById('cameraOverlayText');
                const toggleBtn = document.getElementById('btnToggleCamera');
                const flipBtn = document.getElementById('btnFlipCamera');
                const torchBtn = document.getElementById('btnTorch');

                if (toggleBtn) {
                    toggleBtn.textContent = 'Start Camera';
                    toggleBtn.className = 'btn btn-primary';
                }
                if (flipBtn) flipBtn.disabled = true;
                if (torchBtn) torchBtn.disabled = true;
                if (badge) {
                    badge.textContent = 'Standby';
                    badge.className = 'badge badge-warning';
                }
                if (overlay) overlay.textContent = "Click 'Start Camera' to resume scanning";
            }

            async flipCamera() {
                this.facingMode = (this.facingMode === 'environment') ? 'user' : 'environment';
                if (this.isScanning) {
                    this.stopCamera();
                    await this.startCamera();
                }
            }

            async toggleTorch() {
                if (!this.stream) return;
                const track = this.stream.getVideoTracks()[0];
                try {
                    this.torchState = !this.torchState;
                    await track.applyConstraints({ advanced: [{ torch: this.torchState }] });
                    const torchBtn = document.getElementById('btnTorch');
                    if (torchBtn) {
                        torchBtn.className = this.torchState ? 'btn btn-primary' : 'btn btn-outline';
                    }
                } catch(e) {}
            }

            playBeepSound() {
                if (!this.hapticEnabled) return;
                try {
                    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);

                    if (!this.audioCtx) {
                        this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
                    }
                    const osc = this.audioCtx.createOscillator();
                    const gain = this.audioCtx.createGain();
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(880, this.audioCtx.currentTime);
                    gain.gain.setValueAtTime(0.15, this.audioCtx.currentTime);
                    gain.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + 0.18);
                    osc.connect(gain);
                    gain.connect(this.audioCtx.destination);
                    osc.start();
                    osc.stop(this.audioCtx.currentTime + 0.18);
                } catch(e) {}
            }

            async runScanLoop() {
                const video = document.getElementById('mobileCameraVideo');

                while (this.isScanning) {
                    if (video && video.readyState === video.HAVE_ENOUGH_DATA && !this.isProcessingScan) {
                        try {
                            let detectedRawValue = null;
                            if (this.barcodeDetector) {
                                const barcodes = await this.barcodeDetector.detect(video);
                                if (barcodes && barcodes.length > 0) detectedRawValue = barcodes[0].rawValue;
                            } else if (this.zxingReader && this.zxingCanvas) {
                                const frameWidth = video.videoWidth;
                                const frameHeight = video.videoHeight;
                                if (!frameWidth || !frameHeight) {
                                    throw new Error('Camera frame is not ready');
                                }
                                const scale = Math.min(1, 1280 / frameWidth);
                                this.zxingCanvas.width = Math.max(1, Math.floor(frameWidth * scale));
                                this.zxingCanvas.height = Math.max(1, Math.floor(frameHeight * scale));
                                const ctx = this.zxingCanvas.getContext('2d', { willReadFrequently: true });
                                if (!ctx) throw new Error('Camera canvas is unavailable');
                                ctx.drawImage(
                                    video,
                                    0,
                                    0,
                                    frameWidth,
                                    frameHeight,
                                    0,
                                    0,
                                    this.zxingCanvas.width,
                                    this.zxingCanvas.height
                                );
                                const result = await this.zxingReader.decodeFromCanvas(this.zxingCanvas);
                                detectedRawValue = result.getText();
                            }

                            if (detectedRawValue) {
                                const serial = detectedRawValue.trim().toUpperCase();
                                const now = Date.now();
                                if (serial !== this.lastScannedSerial || (now - this.lastScanTime) > 3000) {
                                    this.lastScannedSerial = serial;
                                    this.lastScanTime = now;
                                    await this.handleBarcodeDetected(serial);
                                }
                            }
                        } catch(err) {}
                    }
                    await new Promise(r => setTimeout(r, this.zxingReader ? 220 : 120));
                }
            }

            submitManualSerial() {
                const deskInput = document.getElementById('mobileManualSerial');
                const modalInput = document.getElementById('mobileManualSerialModal');
                const val = (deskInput && deskInput.value) ? deskInput.value : (modalInput ? modalInput.value : '');
                const serial = val.trim();
                if (!serial || this.isProcessingScan) return;
                if (deskInput) deskInput.value = '';
                if (modalInput) modalInput.value = '';
                this.handleBarcodeDetected(serial.toUpperCase());
            }

            closeBottomSheet() {
                const sheet = document.getElementById('warrantyBottomSheet');
                if (sheet) sheet.classList.add('hidden');
            }

            async printCurrentSheetLabel() {
                if (!this.currentSheetSerial) return;
                const btn = document.getElementById('btnSheetPrint');
                if (btn) btn.textContent = 'Sending to printer...';
                try {
                    const res = await fetch(`/api/scan?serial=${encodeURIComponent(this.currentSheetSerial)}&print=true`);
                    const data = await res.json();
                    const printOk = !!(data.print_result && data.print_result.success);
                    if (btn) btn.textContent = printOk ? 'Label Sent Successfully!' : 'Print Error';
                } catch(e) {
                    if (btn) btn.textContent = 'Print Failed';
                }
            }

            async handleBarcodeDetected(serial) {
                this.isProcessingScan = true;
                this.currentSheetSerial = serial;
                this.playBeepSound();

                const reticle = document.getElementById('cameraReticle');
                const overlay = document.getElementById('cameraOverlayText');
                const autoPrint = this.autoPrintEnabled;

                if (reticle) reticle.classList.add('scan-success');
                if (overlay) overlay.textContent = `Barcode Detected: ${serial} — Fetching Warranty...`;

                try {
                    const res = await fetch(`/api/scan?serial=${encodeURIComponent(serial)}&print=${autoPrint}`);
                    const data = await res.json();

                    // Pokédex / Google Lens Instant Card Overlay
                    const sheet = document.getElementById('warrantyBottomSheet');
                    const sheetVendor = document.getElementById('sheetVendorBadge');
                    const sheetStatus = document.getElementById('sheetStatusBadge');
                    const sheetSerial = document.getElementById('sheetSerialNumber');
                    const sheetModel = document.getElementById('sheetModelName');
                    const sheetEnd = document.getElementById('sheetEndDate');
                    const sheetTier = document.getElementById('sheetTier');
                    const printBtn = document.getElementById('btnSheetPrint');

                    if (sheetVendor) sheetVendor.textContent = data.vendor || 'UNKNOWN';
                    if (sheetStatus) {
                        sheetStatus.textContent = data.status || 'UNVERIFIED';
                        const statusText = String(data.status).toLowerCase();
                        const isOk = statusText.includes('active') || statusText.includes('valid') || statusText.includes('ready');
                        sheetStatus.className = `badge ${isOk ? 'badge-success' : 'badge-danger'}`;
                    }
                    if (sheetSerial) sheetSerial.textContent = `SN: ${data.serial || serial}`;
                    if (sheetModel) sheetModel.textContent = `${data.vendor || ''} ${data.model || ''}`;
                    if (sheetEnd) sheetEnd.textContent = data.expiration_date || 'N/A';
                    const primaryEntitlement = Array.isArray(data.entitlements) && data.entitlements.length > 0
                        ? data.entitlements[0].service
                        : null;
                    if (sheetTier) sheetTier.textContent = primaryEntitlement || 'Standard Coverage';
                    if (printBtn) printBtn.textContent = 'Print 1 Warranty Label';

                    if (sheet) sheet.classList.remove('hidden');
                    if (overlay) overlay.textContent = `Scanned ${serial} (${data.status})`;
                } catch(err) {
                    if (overlay) overlay.textContent = `Error looking up serial ${serial}`;
                } finally {
                    setTimeout(() => {
                        if (reticle) reticle.classList.remove('scan-success');
                        this.isProcessingScan = false;
                    }, 800);
                }
            }
        }
        window.mobileScannerPlugin = new MobileCameraScannerPluginController();
        </script>
        """

    def handle_api_get(self, path: str, query_params: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
        if path in ("/api/plugins/mobile_camera_scanner/info", "/api/plugins/mobile_camera_scanner/pairing"):
            return 200, {
                "success": True,
                "local_ip": get_local_ip(),
                "plugin_id": self.plugin_id,
            }
        return None
