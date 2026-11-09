# NetPulse — Windows Network Quality & Outage Monitor for Sri Lanka

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://github.com/sivanujan/NetPulse)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-PySide6%20%28Qt6%29-41CD52?logo=qt&logoColor=white)](https://wiki.qt.io/Qt_for_Python)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Target](https://img.shields.io/badge/ISPs-Dialog%20%7C%20SLT--Mobitel%20%7C%20Hutch%20%7C%20Airtel-orange)](https://github.com/sivanujan/NetPulse)
[![Disputes](https://img.shields.io/badge/TRCSL-Complaint%20Evidence%20Ready-red)](https://www.trc.gov.lk/)

> **A native Windows desktop utility engineered to monitor, log, visualize, and prove broadband quality issues, ping jitter, packet loss, and outages across Dialog Axiata, SLT-Mobitel, Hutch, and Airtel Sri Lanka.**  
> Features a sleek floating desktop mini-widget, background speed tests, evening peak congestion tracking, and one-click TRCSL complaint evidence pack generation (PDF, PNG, CSV).

---

## 🇱🇰 Why NetPulse Was Built (The Sri Lankan Internet Reality)

In Sri Lanka, millions of users and remote professionals rely on **4G LTE Fixed Broadband (Dialog / SLT Routers)**, **SLT Fibre**, or **mobile USB tethering (iPhone / Android)**.

Subscribers frequently face:
1. **Severe Evening Peak Congestion (6:00 PM – 10:00 PM)**: Base stations become oversaturated, causing ping latency to spike from 50 ms to over 350 ms and packet loss to jump above 20%.
2. **Rural & Suburban Signal Fluctuations**: Weak 4G signal causes random disconnects and micro-outages lasting 1–3 minutes.
3. **The "Restart Your Router" Trap**: When you call ISP customer support (Dialog 1777, SLT 1212, Mobitel 1717), customer service representatives routinely claim *"our system shows your line is normal"* or ask you to reboot your device.
4. **Data-Wasting Speed Tests**: Running commercial speed tests (Speedtest.net, Fast.com) burns 150 MB – 500 MB of your precious monthly quota per test.

**NetPulse changes the game.**  
It runs quietly in the background, continuously records network health without eating your data quota, and gives you **irrefutable evidence** with timestamped outage logs and graphical reports ready to submit to **TRCSL (Telecommunications Regulatory Commission of Sri Lanka)** and your service provider.

---

## 🌟 Key Features

### 1. 🖥️ Desktop Floating Mini-Widget (Always at a Glance)
A compact, modern, semi-transparent card (260×110 px) floating on your desktop:
- **Big Live Ping Display**: Color-coded by quality (Green < 100 ms, Amber 100–300 ms, Red > 300 ms, Grey = Disconnected).
- **Status Indicator & Unit**: Shows both number and status word (`Good`, `Slow`, `Bad`, `Down`) with accurate `ms` typography.
- **Provider & Connection Type**: Detects whether you are on **Dialog**, **Mobitel**, **SLT**, or **Hutch**, and identifies connection mode (*iPhone USB*, *Android Tether*, *Ethernet*, or *WiFi with SSID*).
- **10-Minute Rolling Sparkline**: Live trendline showing latency fluctuations with peak annotation (`max 312 ms`).
- **Live Local PC Traffic Throughput**: Shows current upload/download rates (`kbps` or `Mbps`) on the active adapter with automatic warning if local background upload exceeds 500 kbps for 3+ minutes.
- **Customizable**: Draggable with multi-monitor position memory, opacity slider, always-on-top, click-through, and compact/expanded modes.

### 2. 📊 Modern Windows 11 Dashboard
- **Live Vitals Page**: Real-time gauge, rolling 1-hour latency and loss graphs, and active adapter bandwidth.
- **Today's Overview**: 6 primary KPIs (Uptime %, Good Quality %, Median Ping, Download Speed, Total Outages, Peak Congestion Hours) and a 24-hour hourly latency bar chart highlighting the **Sri Lankan Evening Window (18:00 – 22:00)**.
- **History & Analytics**: Presets (*Today, Yesterday, Last 24 Hours, Last 7 Days, Last 30 Days, All Time, Custom*), provider/connection filter dropdowns, 4 synchronized timeseries plots, and red-shaded outage blocks.
- **Compare Networks**: Head-to-head performance scorecard comparing Dialog vs. Mobitel vs. SLT vs. Hutch with winner badges (*Best Overall*, *Best Evening Peak*) and fairness warnings.
- **Outages Log**: Chronological incident ledger tracking every complete disconnect (`DOWN`) and sustained degradation (`BAD > 5 min`), duration in minutes/seconds, and check counts.
- **Settings**: Fully customizable ping hosts, speed test intervals (15 min / 30 min / 1 hour / 3 hours / Off), data-saver mode, and subscriber details.

### 3. 📄 TRCSL & ISP Complaint Evidence Pack Generator
Export professional, legally sound dispute documentation in seconds:
- **High-Resolution Vector PDF & PNG**: Formatted with subscriber name, service address, analysis period, executive summary KPI table, download speed timeline, ping latency with outage shading, and 24-hour evening congestion profile.
- **Local PC Traffic Proof**: Proves to the ISP that high latency or packet loss was **not** caused by local PC downloads or torrents.
- **Filtered CSV Export**: Raw timestamps and metrics formatted for direct email attachment to **TRCSL Consumer Complaints Division** (`cc@trc.gov.lk`).

### 4. 🚀 Ultra-Lightweight & Quota-Friendly
- **Smart Multi-Host Ping**: Concurrently checks `8.8.8.8` (Google) and `1.1.1.1` (Cloudflare). Uses the better host's loss so external DNS blocks never fake 50% loss.
- **Lightweight Speed Tests**: Measures true throughput using Cloudflare edge endpoints capped at 5 MB (or 10 MB on high-speed fiber), preventing monthly quota drain.
- **Data-Saver Mode**: Easily drop ping frequency and turn off automatic speed tests with 1 click.
- **Windows Toast Alerts**: Rate-limited notifications for disconnects > 60 s, network restoration, provider handovers, and high background uploads.

---

## 🛠️ Architecture & Data Privacy Guarantee

NetPulse is built with an **offline-first, zero-telemetry** architecture:

```
[ Active Network Adapter ]
         │
         ▼
[ Core Monitor Engine ] ──(Every 30s)──> [ net_log.csv ] (Append-only Source of Truth)
         │                                       │
         ▼                                       ▼
[ Local SQLite Cache (WAL) ] <─────────── [ Background Sync ]
         │
         ├──> [ Floating Desktop Mini Widget ]
         ├──> [ Windows System Tray Icon ]
         ├──> [ 5-Page Windows 11 Dashboard ]
         └──> [ TRCSL Complaint Report Generator (PDF/PNG/CSV) ]
```

- **100% Private**: All logs (`net_log.csv`, `speed_log.csv`, `netpulse_cache.db`) stay strictly on your local computer.
- **Zero Cloud Sending**: No data is ever sent to external servers, telemetry services, or analytics providers.
- **Permanent Source of Truth**: CSV files remain standard, open, and human-readable.

---

## 📦 Installation & Setup

### Option 1: 1-Click Installer to C: Drive (Recommended for Users)

NetPulse includes an automated Windows installer that sets up the app permanently on your **C: drive**:

1. Clone or download the repository:
   ```cmd
   git clone https://github.com/sivanujan/NetPulse.git
   cd NetPulse
   ```
2. Double-click or run:
   ```cmd
   install.bat
   ```

**What the installer does automatically:**
- Installs NetPulse to `C:\Users\<User>\AppData\Local\Programs\NetPulse\`.
- Creates a **Desktop Shortcut** (`NetPulse`).
- Creates a **Start Menu Shortcut** (searchable in Windows Start).
- Registers **Start with Windows** (`HKCU\...\Run`), so it starts silently in the background when your PC boots.
- Safely copies your monitoring logs to `%APPDATA%\NetPulse`.
- Generates a 1-click `uninstall.bat`.

---

### Option 2: Run from Source (For Developers)

1. **Clone repository**:
   ```cmd
   git clone https://github.com/sivanujan/NetPulse.git
   cd NetPulse
   ```
2. **Install Python dependencies**:
   ```cmd
   pip install -r requirements.txt
   ```
3. **Launch the application**:
   ```cmd
   python app.py
   ```
   *(Or run silently in background without console: `pythonw app.py`).*

4. **Run Unit Tests**:
   ```cmd
   python -m unittest discover tests -v
   ```
   *(All 43 unit tests execute offscreen in < 5 seconds).*

5. **Dry-Run Network Test (No CSV writes)**:
   ```cmd
   python -m core.monitor --once
   ```

---

### Option 3: Compile to Standalone Executable (.exe)

To build a fresh standalone Windows executable (`dist\NetPulse\NetPulse.exe`):

```cmd
build.bat
```

This compiles a high-performance one-folder executable bundling the Python runtime, PySide6, PyQtGraph, and Matplotlib.

---

## 📝 How to File a Dispute with TRCSL & Sri Lankan ISPs

If you are experiencing persistent slow speeds, disconnects, or evening latency spikes:

1. Let NetPulse run continuously for **24 to 72 hours** to collect statistical evidence.
2. Open the NetPulse Dashboard $\rightarrow$ click **📄 Create Report** in the sidebar.
3. Select your date range (e.g. *Last 7 Days* or *Last 30 Days*) and your provider (e.g. *Dialog*, *Mobitel*, or *SLT*).
4. Click **Create PDF & PNG Report**.
5. Submit your formal complaint:
   - **Service Provider Formal Complaint**:
     - **Dialog Broadband**: Call 1777 or email `service@dialog.lk`
     - **SLT-Mobitel Home Broadband**: Call 1212 / 1717 or submit via MySLT Portal
     - **Hutch Sri Lanka**: Call 1788 or email `cs@hutchison.lk`
   - **TRCSL Consumer Protection Division**:
     - Email: `cc@trc.gov.lk`
     - Website: [https://www.trc.gov.lk](https://www.trc.gov.lk)
     - Attach the generated **NetPulse PDF Report** and **Filtered CSV Export** as certified technical evidence.

---

## ⌨️ Controls & Shortcuts

| Action | Control |
| :--- | :--- |
| **Open Dashboard** | Double-click desktop widget OR click tray icon menu $\rightarrow$ *Open Dashboard*. |
| **Move Floating Widget** | Click and drag the widget anywhere on any connected monitor. |
| **Start with Windows** | Right-click tray icon $\rightarrow$ check **Start with Windows** (or in Settings). |
| **Pause Monitoring** | Right-click tray icon $\rightarrow$ *Pause Monitoring (15 min / 1 h / Until resume)*. |
| **Manual Speed Test** | Right-click tray icon $\rightarrow$ *Run Speed Test Now*. |
| **Export Evidence Pack** | Dashboard sidebar $\rightarrow$ *📄 Create Report* (or tray menu $\rightarrow$ *Create Report*). |
| **Exit Application** | Right-click tray icon $\rightarrow$ *Quit*. |
| **Uninstall** | Run `uninstall.bat` inside `C:\Users\<User>\AppData\Local\Programs\NetPulse\`. |

---

## 🔍 SEO & Search Discovery Tags

Sri Lanka Internet Monitor · Dialog Axiata 4G Ping Test · SLT Mobitel Broadband Outages · Hutch Sri Lanka Speed Test · Airtel Sri Lanka · TRCSL Complaint Evidence Generator · Telecommunications Regulatory Commission of Sri Lanka · Windows Desktop Ping Widget · Floating Network Quality Monitor · Packet Loss & Jitter Tracker · Sri Lanka Evening Peak Congestion · iPhone USB Tethering Monitor · Android USB Tethering Network Quality · PySide6 Windows 11 Network Utility · ISP Dispute PDF Generator.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE). Built for the Sri Lankan developer, remote worker, and gaming community.
