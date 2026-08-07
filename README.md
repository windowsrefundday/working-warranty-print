# Warranty Label Printer

A source-only warranty lookup and label-printing tool for IT departments. Scan
an HP or Lenovo serial number, verify warranty information against the vendor,
and create a 3 × 1 inch label. The same application runs on Windows and macOS;
Windows 11 x64 is the primary supported deployment.

## Quick Start (First-Time Windows Setup)

Follow these steps to install and run the application on a Windows 10 / 11 computer:

### Step 1: Open the Web Page
Open this repository page (`github.com/windowsrefundday/working-warranty-print`) on the Windows computer where you want to install the software.

### Step 2: Open PowerShell
1. Click the **Start Menu** (or press `Win + R`).
2. Search for **PowerShell** (make sure the title bar or terminal prompt says **PowerShell**, not Command Prompt).

### Step 3: Copy and Paste the Installation Command
Copy the following command from the web page and paste it into your PowerShell window, then press **Enter**:

```powershell
irm https://raw.githubusercontent.com/windowsrefundday/working-warranty-print/main/install.ps1 | iex
```

> **Note:** No Administrator rights are required. This script uses `winget` (if installed) to fetch Git and Python 3.11, clones the repo to `%USERPROFILE%\working-warranty-print`, creates Start Menu and Desktop shortcuts, and launches the operator menu.

### Step 4: Navigate the Operator CLI Menu
Once installation completes, the interactive operator menu will automatically launch in PowerShell:

```text
============================================================
  WARRANTY LABEL PRINTER - WINDOWS OPERATOR MENU
============================================================
  1. Start CLI printer mode
  2. Start CLI safe mode (virtual text files, no printing)
  3. Start web mode with secure Tunnel
  4. Run printer diagnostic check
  5. Update application (git pull)
  6. Run environment setup
  7. Run printer setup
  8. Run label calibration test
  9. Create Windows shortcuts
  0. Exit
============================================================
```

#### Common Actions:
- **`1` (CLI Printer Mode)**: Launches barcode scanning mode connected to your thermal printer. Simply scan or type a serial number and press **Enter**.
- **`2` (Safe Mode)**: Test lookups without a physical printer attached (outputs virtual text files).
- **`3` (Web Mode)**: Starts local web server dashboard with secure remote camera scanning tunnel.
- **`7` (Printer Setup)**: Choose or change which connected USB thermal printer to bind.
- **`q` or `0`**: Exit the menu or CLI scanner.

---

## One-Liner Windows Uninstallation

To completely remove the application, local data cache, and shortcuts (while leaving Python and Git installed on the computer), open PowerShell and paste:

```powershell
irm https://raw.githubusercontent.com/windowsrefundday/working-warranty-print/main/uninstall.ps1 | iex
```

---

## Public-release safety

This repository contains source code and synthetic test fixtures only. Do not
commit warranty exports, serial numbers, labels, logs, printer bindings,
profiles, caches, `.env` files, or credentials. The release audit is designed to
fail closed on those artifacts; run it before publishing:

```bash
python tools/release_audit.py
```

Live vendor lookup failures remain unverified and cannot create labels. Treat
serial numbers, warranty results, CSV exports, and generated labels as
sensitive operational data. Keep them in the per-user runtime data directory,
not in the checkout or an issue, pull request, log, screenshot, or support
attachment.

The web dashboard is local by default. For phone access, use the documented
HTTPS tunnel mode and the one-time QR pairing link. Do not port-forward the
dashboard, expose the raw HTTP port, or paste pairing URLs into chat or public
tickets. Stop the tunnel when finished and remember that a tunnel provider can
observe traffic metadata.

## License and vulnerability reports

This independently owned project is released under the [Apache License 2.0](LICENSE).
If an agency, employer, or contractor owns the code, its legal and release
policy must replace this assumption before publication. Report security issues
privately using the process in [SECURITY.md](SECURITY.md); do not open a public
issue for an unpatched vulnerability.

## Quick start: use the web scanner

If you only want to use the browser dashboard, you do not need a printer or
Node.js. Setup installs Python dependencies and Chromium, then runs read-only
diagnostics.

On Windows, open PowerShell in the repository folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup-windows.ps1
.\warranty-windows.ps1 web -Port 9191
```

On macOS, open Terminal in the repository folder and run:

```bash
./setup-macos.sh
.venv/bin/python main.py --mode web --port 9191
```

Then open `http://localhost:9191` on the computer. This local mode is enough
to test the dashboard and scanner from that computer.

For phone-camera access from another device, you need a public HTTPS tunnel.
Install Node.js LTS first, then run setup with the tunnel runtime enabled:

```powershell
.\setup-windows.ps1 -WithTunnelRuntime
.\warranty-windows.ps1 web -Port 9191 -Tunnel
```

```bash
./setup-macos.sh --with-tunnel-runtime
.venv/bin/python main.py --mode web --port 9191 --tunnel
```

Keep the computer's terminal open and scan the secure pairing QR code shown in
the dashboard with your phone. Without the tunnel setup step, `--tunnel` will
stop with an explanatory missing-runtime error.

## What the application protects against

- Unverified, incomplete, or stale warranty results cannot create labels.
- A physical job requires one explicitly selected, ready TSC MB341 USB queue.
- The printer model, 300-dpi capability, USB connection, and queue state are
  rechecked immediately before submission.
- Each scan creates at most one copy. There is no automatic retry, default
  printer, or alternate-printer fallback.
- If the physical printer is unavailable, CLI startup falls back visibly to
  virtual text files.
- Setup and diagnostics never print or calibrate.

## Windows 11 x64 setup

### 1. Before you begin

You need:

- Windows 11 on an Intel/AMD 64-bit PC. Windows ARM is not supported.
- Administrator access only for installing Python and the official printer
  driver. Daily use does not require an administrator PowerShell.
- [64-bit Python 3.11 or newer](https://www.python.org/downloads/windows/).
  During Python setup, enable **Add python.exe to PATH**.
- [Git for Windows](https://git-scm.com/download/win), unless you use GitHub’s
  **Download ZIP** option.
- A TSC MB341 connected directly to the PC by USB, powered on, loaded with the
  approved 76.2 × 25.4 mm stock, and showing no printer error.

Do not connect through TCP/IP, a shared print server, Remote Desktop printer
redirection, or a generic text driver.

### 2. Install the official TSC driver

1. Open the [official TSC downloads page](https://usca.tscprinters.com/en/downloads).
2. Filter/select **MB341**.
3. Download and install the **WHQL-certified Windows x64 driver**.
4. Connect the MB341 directly by USB and turn it on.
5. Open **Settings → Bluetooth & devices → Printers & scanners**.
6. Confirm a TSC MB341 queue exists, is online, and is not paused.

The repository does not download or execute printer-driver installers.

### 3. Download the code

Recommended Git workflow:

```powershell
git clone <repository-url>
cd warranty-label-printer
```

Without Git, choose **Code → Download ZIP** on GitHub, select **Extract All**,
then open PowerShell inside the extracted `warranty-label-printer` folder.
Paths containing spaces are supported.

To confirm you are in the correct folder:

```powershell
Get-ChildItem
```

You should see `main.py`, `setup-windows.ps1`, and
`warranty-windows.ps1`.

### 4. Run automated setup

PowerShell blocks local scripts on some PCs. The first command changes policy
for this PowerShell window only:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\warranty-windows.ps1 setup
```

Setup performs five visible steps. If you choose `-WithTunnelRuntime`, it adds
one sixth step before the final diagnostics to install the locked localtunnel
runtime:

1. Confirms 64-bit Python 3.11+.
2. Creates or refreshes `.venv` inside the repository.
3. Installs pinned shared dependencies plus `pywin32`.
4. Attempts to install the Playwright Chromium browser used for vendor lookups.
5. Runs read-only system, browser, storage, driver, and queue checks.

It is safe to rerun setup after an update or interrupted dependency install.
Node.js is not needed for this basic setup. To enable phone-camera tunnel mode,
install Node.js LTS and rerun `.\setup-windows.ps1 -WithTunnelRuntime`.

If a corporate HTTPS proxy blocks the Playwright browser download with a
certificate-chain error, setup reports a warning and continues to diagnostics.
On Windows, vendor workers then try the installed Microsoft Edge and Google
Chrome browsers after bundled Chromium. If your organization provides a
trusted proxy CA certificate, pass it only to the browser download stage:

```powershell
.\setup-windows.ps1 -BrowserCaCert C:\path\to\corporate-root.pem
```

Setup never disables TLS verification globally. If no browser runtime is
available, live vendor lookups fail closed instead of fabricating warranty data.

### 5. Bind the USB printer

Printer binding is deliberately separate from setup:

```powershell
.\warranty-windows.ps1 printer
```

The tool lists only validated local USB MB341 queues. Enter the number beside
the correct queue. The exact queue, driver, port, model, and DPI are saved under
your Windows profile. The application never silently chooses the Windows
default printer.

If no queue is listed, run:

```powershell
.\warranty-windows.ps1 doctor
```

Then correct the reported driver, USB, offline, or paused-queue problem before
trying again.

### 6. Prove lookups safely before printing

Start in virtual-file mode:

```powershell
.\warranty-windows.ps1 safe
```

Scan or type a supported asset serial and press Enter. A successful verified
lookup creates a readable label file in:

```text
%LOCALAPPDATA%\WarrantyLabelPrinter\labels
```

Use `q` to quit. Do not proceed to physical output until HP/Lenovo lookup
results and the virtual label contents are correct.

### 7. Start normal scanner mode

```powershell
.\warranty-windows.ps1 cli
```

The startup banner clearly shows either:

- `Physical Printing: ENABLED` with the TSC MB341 connector; or
- `DISABLED (Virtual File Output Only)` when validation fails.

Useful commands inside the scanner:

| Command | Action |
| --- | --- |
| `printers` | Show the validated TSC queue |
| `tsc` | Select the validated physical connector |
| `file` | Force safe virtual-file output |
| `setup` | Repeat the explicit printer-binding workflow |
| `calibrate` | Print exactly one dedicated `TEST123` layout label |
| `sensorcal` | Feed media and recalibrate the gap sensor |
| `q` | Shut down browser workers and exit |

`sensorcal` is not a routine test. It can feed several labels and should only
be used when approved stock is loaded and labels are skipping.

## Windows operator helper

All common tasks use one script:

```powershell
.\warranty-windows.ps1 help
.\warranty-windows.ps1 setup
.\warranty-windows.ps1 doctor
.\warranty-windows.ps1 printer
.\warranty-windows.ps1 safe
.\warranty-windows.ps1 cli
.\warranty-windows.ps1 web -Port 9191
.\warranty-windows.ps1 verify
```

`verify` runs unit tests and Python compilation. It also runs Pyright when
Node.js/`npx` is installed. None of these verification commands contacts a
physical printer.

## Web and phone-camera mode

Start the local web dashboard:

```powershell
.\warranty-windows.ps1 web -Port 9191
```

Open `http://localhost:9191` on the PC. For phone-camera scanning, start a
temporary HTTPS tunnel instead:

```powershell
.\warranty-windows.ps1 web -Port 9191 -Tunnel
```

Keep the PowerShell window open, then scan the dashboard's secure pairing QR
code. The pairing link contains a random token that is valid only for that
server process. Allow Python through Windows Firewall only on trusted private
networks.

Without `-Tunnel`, the local dashboard remains available but remote phone camera
access is intentionally blocked because mobile browsers require HTTPS. The
tunnel also avoids corporate Wi-Fi client isolation; both devices still need
internet access.

On macOS, run the same modes after `./setup-macos.sh`:

```bash
.venv/bin/python main.py --mode web --port 9191
.venv/bin/python main.py --mode web --port 9191 --tunnel
```

Tunnel mode requires Node.js/npm and the optional tunnel setup step. That step
installs the reviewed, lockfile-pinned tunnel dependency with `npm ci`; the app
does not download a tunnel tool at launch.

## Windows troubleshooting

### “Running scripts is disabled”

Open a new PowerShell in the repository and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

If the code came from a ZIP and Windows still blocks it:

```powershell
Get-ChildItem -Recurse | Unblock-File
```

### “Python was not found”

Install 64-bit Python from python.org, select **Add python.exe to PATH**, close
all PowerShell windows, open a new one, and rerun setup.

### “The term .\warranty-windows.ps1 is not recognized”

You are in the wrong directory or the ZIP was not extracted. Use `Get-ChildItem`
and navigate to the folder containing `main.py`.

### No printer candidate appears

1. Verify the device is an MB341, not an MB340 or another TSC model.
2. Confirm it is directly connected by USB and powered on.
3. Confirm the official TSC driver—not a generic driver—is assigned.
4. Open the Windows print queue and clear paused/offline/error states.
5. Run `.\warranty-windows.ps1 doctor`, then `printer`.

The first Windows release intentionally rejects TCP/IP ports, shared queues,
default-printer selection, wrong models, non-300-dpi queues, and Windows ARM.

### Chromium or vendor lookup fails

Rerun setup to repair Chromium:

```powershell
.\warranty-windows.ps1 setup
```

For an interactive vendor challenge, temporarily launch with visible browsers:

```powershell
$env:HP_WARRANTY_HEADLESS="0"
$env:LENOVO_WARRANTY_HEADLESS="0"
.\warranty-windows.ps1 safe
```

These variables last only for the current PowerShell window.

### Warranty is shown but printing is blocked

Printing requires `VERIFIED LIVE` evidence or eligible verified cache evidence.
Resolver-only, mismatched, incomplete, failed, or cache entries older than 30
days fail closed. Do not bypass this gate; fix the vendor lookup.

### Label alignment or skipped labels

Do not edit the built-in profile first. Confirm the approved stock is loaded,
the guides are snug, the gap sensor is positioned correctly, and the saved
queue is 300 dpi. Use `calibrate` for one layout test. Use `sensorcal` only for
a confirmed media-sensing problem.

## Updating an existing checkout

```powershell
git pull
Set-ExecutionPolicy -Scope Process Bypass
.\warranty-windows.ps1 setup
.\warranty-windows.ps1 doctor
```

Setup preserves local application data and the explicit printer binding.

## macOS secondary setup

macOS uses the same warranty, TSPL, profile, CLI, web, and safety modules. Only
CUPS discovery/raw submission, scanner input, and application-data paths differ.

```bash
git clone <repository-url>
cd warranty-label-printer
chmod +x setup-macos.sh run-macos.sh
./setup-macos.sh
./run-macos.sh
```

For the browser dashboard or phone camera, use the commands in
[Web and phone-camera mode](#web-and-phone-camera-mode) after setup. The QR
pairing link is valid only for the running server process.

The expected queue is `TSC_MB341`. It must identify as a USB TSC MB341, accept
jobs, be ready, and expose 300-dpi capability. macOS mutable data is stored in:

```text
~/Library/Application Support/WarrantyLabelPrinter
```

## Configuration and data

Optional environment settings are documented in `.env.example`.

| Setting | Purpose |
| --- | --- |
| `WARRANTY_LABEL_DATA_DIR` | Override the native per-user data directory |
| `HP_WARRANTY_HEADLESS` | `1` for hidden browser, `0` for visible |
| `HP_WARRANTY_PRELOAD` | Prewarm the HP browser worker |
| `LENOVO_WARRANTY_HEADLESS` | `1` for hidden browser, `0` for visible |
| `LENOVO_WARRANTY_PRELOAD` | Prewarm the Lenovo browser worker |

The shared immutable profile
`tsc-mb341-300dpi-3x1-warranty-v1` is 76.2 × 25.4 mm with a 3 mm gap, 300 dpi,
darkness 11, speed 50, X offset 2.4 mm, Y shift 0, and one copy.

## Architecture and development

```text
core/
  application/       Platform composition
  label_formatters/  Shared TSPL and virtual label rendering
  printers/          Bindings, profiles, discovery, and RAW transports
  vendors/           HP and Lenovo lookup/verification
interfaces/          CLI, web, scanners, and web plugins
tests/               unittest suite with mocked hardware/browser boundaries
```

macOS uses CUPS (`lpstat`, `lpoptions`, and raw `lp`). Windows uses the spooler
through `pywin32` (`OpenPrinter`, `StartDocPrinter` with datatype `RAW`,
`WritePrinter`, and `EndDocPrinter`). Both submit the exact same TSPL bytes.

Developer checks:

```powershell
.\warranty-windows.ps1 verify
```

or directly:

```bash
python -m unittest discover -s tests -v
python -m compileall -q core interfaces main.py tests
npx pyright
```

Automated tests inject fake transports and must never submit a physical job,
change calibration, use a default printer, or weaken warranty verification.
