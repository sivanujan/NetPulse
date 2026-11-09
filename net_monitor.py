#!/usr/bin/env python3
"""
net_monitor.py  v2 - Home internet monitor
(ping, packet loss, download speed, which connection/provider, PC usage)

ONE-TIME SETUP
    pip install matplotlib

COMMANDS  (run from the folder where this file is)
    python net_monitor.py start          start in the BACKGROUND (no window)
    python net_monitor.py stop           stop the background monitor
    python net_monitor.py status         is it running? current network + last checks
    python net_monitor.py autostart on   start automatically when Windows logs in
    python net_monitor.py autostart off  remove auto start
    python net_monitor.py monitor        run in this window (Ctrl+C to stop)

    python net_monitor.py networks                       list networks seen so far
    python net_monitor.py report                         full report (all data)
    python net_monitor.py report --network Dialog        only Dialog
    python net_monitor.py report --network "iPhone USB"  only iPhone USB tethering
    python net_monitor.py report --hours 24              only last 24 hours
    python net_monitor.py report --date 2026-11-06       only one day

All files are kept next to this script:
    net_log.csv      every 30 s : ping, loss, status, connection, provider, PC usage
    speed_log.csv    every 15 min: download speed + connection + provider
    monitor.log      background messages
    net_report.png   the graph       net_summary.txt   the text summary

Provider is detected from your public IP (ipinfo.io), every 2 minutes,
so switching SIM on the phone is picked up automatically.
DATA USE: speed test <= ~5 MB each (stops after 10 s); every 15 min = <= ~480 MB/day.
"""

import csv
import glob
import json
import os
import platform
import re
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta

# ---------------- settings ----------------
PING_HOSTS = ["8.8.8.8", "1.1.1.1"]
PING_COUNT = 4
CHECK_INTERVAL_SEC = 30
SPEED_INTERVAL_SEC = 15 * 60
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=5000000"
SPEED_MAX_SEC = 10
ISP_INTERVAL_SEC = 120            # re-check provider every 2 min
ADAPTER_INTERVAL_SEC = 300        # re-check adapter every 5 min (or when IP changes)
DNS_TEST_NAME = "www.google.com"
BUSY_KBPS = 300                   # PC traffic above this = "you were using the internet"
# ------------------------------------------

BASE = os.path.dirname(os.path.abspath(__file__))
NET_LOG = os.path.join(BASE, "net_log.csv")
SPEED_LOG = os.path.join(BASE, "speed_log.csv")
PID_FILE = os.path.join(BASE, "monitor.pid")
LOG_FILE = os.path.join(BASE, "monitor.log")
REPORT_PNG = os.path.join(BASE, "net_report.png")
SUMMARY_TXT = os.path.join(BASE, "net_summary.txt")

NET_HEADER = ["time", "latency_ms", "loss_pct", "dns_ms", "status", "conn", "network",
              "isp", "wifi_signal", "pc_down_kbps", "pc_up_kbps", "local_ip"]
SPEED_HEADER = ["time", "download_mbps", "conn", "network", "isp"]
TFMT = "%Y-%m-%d %H:%M:%S"

IS_WIN = platform.system().lower().startswith("win")
NO_WINDOW = 0x08000000 if IS_WIN else 0     # stop console windows flashing


def now():
    return datetime.now().strftime(TFMT)


def run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              timeout=timeout, creationflags=NO_WINDOW).stdout
    except Exception:
        return ""


# ================= measurements =================
def ping(host, count=PING_COUNT):
    """Return (avg_ms or None, loss_percent)."""
    cmd = (["ping", "-n", str(count), "-w", "2000", host] if IS_WIN
           else ["ping", "-c", str(count), "-W", "2", host])
    out = run(cmd, timeout=count * 3 + 5)
    times = [float(t) for t in re.findall(r"time[=<]\s*([\d.]+)\s*ms", out, re.I)]
    loss = 100.0 * (count - len(times)) / count
    return (sum(times) / len(times) if times else None), loss


def dns_time():
    t0 = time.perf_counter()
    try:
        socket.setdefaulttimeout(5)
        socket.gethostbyname(DNS_TEST_NAME)
        return (time.perf_counter() - t0) * 1000
    except Exception:
        return None


def speed_test():
    """Return (Mbps, bytes downloaded)."""
    req = urllib.request.Request(SPEED_URL, headers={"User-Agent": "net-monitor"})
    got, t0 = 0, time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            while True:
                chunk = r.read(32 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if time.perf_counter() - t0 > SPEED_MAX_SEC:
                    break
    except Exception:
        pass
    secs = max(time.perf_counter() - t0, 0.001)
    return round(got * 8 / secs / 1_000_000, 3), got


# ================= which connection? =================
def local_ip():
    """IP of the adapter used for internet (no traffic is sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def wifi_info():
    """Windows: (ssid, signal%) of the connected Wi-Fi, else ('', '')."""
    if not IS_WIN:
        return "", ""
    out = run(["netsh", "wlan", "show", "interfaces"], timeout=8)
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    sig = re.search(r"^\s*Signal\s*:\s*(\d+)%", out, re.M)
    return (ssid.group(1).strip() if ssid else ""), (sig.group(1) if sig else "")


def adapter_conn(ip):
    """Return a label like 'iPhone USB', 'WiFi: MyHotspot', 'Ethernet'."""
    if not ip:
        return "no connection"
    if not IS_WIN:
        return "unknown"
    ps = ("Get-NetIPAddress -IPAddress '%s' -ErrorAction SilentlyContinue | Get-NetAdapter | "
          "Select-Object -First 1 Name,InterfaceDescription,PhysicalMediaType | ConvertTo-Json" % ip)
    out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=20)
    try:
        info = json.loads(out)
    except Exception:
        info = {}
    desc = f"{info.get('Name', '')} {info.get('InterfaceDescription', '')}".lower()
    media = str(info.get("PhysicalMediaType", "")).lower()
    if "apple mobile device" in desc:
        return "iPhone USB"
    if "rndis" in desc or "remote ndis" in desc:
        return "Android USB"
    if "802.11" in media or "wi-fi" in desc or "wireless" in desc or "wlan" in desc:
        ssid, _ = wifi_info()
        return f"WiFi: {ssid}" if ssid else "WiFi"
    if info:
        return "Ethernet"
    return "unknown"


def short_provider(org):
    o = org.lower()
    for key, name in [("dialog", "Dialog"), ("mobitel", "Mobitel"), ("hutch", "Hutch"),
                      ("airtel", "Airtel"), ("bharti", "Airtel"), ("sri lanka telecom", "SLT"),
                      ("slt", "SLT"), ("lanka bell", "Lanka Bell"), ("starlink", "Starlink"),
                      ("spacex", "Starlink")]:
        if key in o:
            return name
    return re.sub(r"^AS\d+\s+", "", org).strip()[:30] or "unknown"


def isp_lookup():
    """Return (short_name, full org) from the public IP, or None if it failed."""
    try:
        req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "net-monitor"})
        with urllib.request.urlopen(req, timeout=8) as r:
            org = json.loads(r.read().decode()).get("org", "")
        return short_provider(org), org
    except Exception:
        return None


# ================= PC traffic =================
def net_bytes():
    """Total (received, sent) bytes on this PC, or None."""
    try:
        import psutil
        c = psutil.net_io_counters()
        return c.bytes_recv, c.bytes_sent
    except Exception:
        pass
    if IS_WIN:
        m = re.search(r"^\s*Bytes\s+(\d+)\s+(\d+)", run(["netstat", "-e"], timeout=10), re.M)
        if m:
            return int(m.group(1)), int(m.group(2))
    elif os.path.exists("/proc/net/dev"):
        rx = tx = 0
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                name, data = line.split(":", 1)
                if name.strip() == "lo":
                    continue
                p = data.split()
                rx += int(p[0])
                tx += int(p[8])
        return rx, tx
    return None


# ================= file helpers =================
def prepare_log(path, header):
    """If an old-format log exists, keep it under a new name and start fresh."""
    if os.path.exists(path):
        with open(path, newline="") as f:
            first = next(csv.reader(f), [])
        if first != header:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.rename(path, path.replace(".csv", f"_old_{stamp}.csv"))


def append_row(path, header, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def pid_alive(pid):
    if IS_WIN:
        return str(pid) in run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], timeout=10)
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def running_pid():
    try:
        pid = int(open(PID_FILE).read().strip())
        return pid if pid_alive(pid) else None
    except Exception:
        return None


# ================= monitor loop =================
def keep_awake():
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        except Exception:
            pass


def monitor():
    if sys.stdout is None:                      # started with pythonw (background)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 5_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".1")
        sys.stdout = sys.stderr = open(LOG_FILE, "a", buffering=1, encoding="utf-8")

    other = running_pid()
    if other and other != os.getpid():
        print(f"Monitor already running (PID {other}).")
        return
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    keep_awake()
    prepare_log(NET_LOG, NET_HEADER)
    prepare_log(SPEED_LOG, SPEED_HEADER)
    print(f"{now()}  Monitoring started (PID {os.getpid()}). Files in: {BASE}")

    st = {"ip": None, "conn": "unknown", "network": "unknown", "isp": "",
          "t_adapter": 0, "t_isp": 0, "t_speed": 0, "last_status": "OK"}
    prev_bytes, prev_t, speed_bytes = net_bytes(), time.time(), 0

    try:
        while True:
            start = time.time()

            # --- which connection? ---
            ip = local_ip()
            ip_changed = ip != st["ip"]
            if ip_changed or start - st["t_adapter"] > ADAPTER_INTERVAL_SEC:
                st["conn"] = adapter_conn(ip)
                st["t_adapter"] = start
                st["ip"] = ip
            wifi_sig = wifi_info()[1] if st["conn"].startswith("WiFi") else ""

            # --- ping / dns ---
            lat, loss = [], []
            for h in PING_HOSTS:
                a, l = ping(h)
                if a is not None:
                    lat.append(a)
                loss.append(l)
            avg_lat = round(sum(lat) / len(lat), 1) if lat else ""
            avg_loss = round(sum(loss) / len(loss), 1)
            d = dns_time()
            status = ("DOWN" if avg_loss >= 100 else
                      "BAD" if avg_loss >= 25 or (lat and avg_lat > 300) else "OK")

            # --- which provider? (only possible while internet works) ---
            if status != "DOWN" and (ip_changed or st["last_status"] == "DOWN"
                                     or start - st["t_isp"] > ISP_INTERVAL_SEC):
                res = isp_lookup()
                if res:
                    st["network"], st["isp"] = res
                    st["t_isp"] = start

            # --- PC traffic since last check (minus our own speed test) ---
            cur = net_bytes()
            down_k = up_k = ""
            if cur and prev_bytes:
                secs = max(time.time() - prev_t, 1)
                rx = cur[0] - prev_bytes[0] - speed_bytes
                tx = cur[1] - prev_bytes[1]
                if rx >= 0 and tx >= 0:
                    down_k = round(rx * 8 / secs / 1000, 1)
                    up_k = round(tx * 8 / secs / 1000, 1)
            prev_bytes, prev_t, speed_bytes = cur, time.time(), 0

            append_row(NET_LOG, NET_HEADER,
                       [now(), avg_lat, avg_loss, round(d, 1) if d is not None else "", status,
                        st["conn"], st["network"], st["isp"], wifi_sig, down_k, up_k, ip])
            print(f"{now()}  [{status:4}] ping={avg_lat or '---'} ms loss={avg_loss}%  "
                  f"{st['network']} via {st['conn']}  PC down/up={down_k}/{up_k} kbps")

            # --- speed test ---
            if time.time() - st["t_speed"] >= SPEED_INTERVAL_SEC:
                mbps, got = speed_test() if status != "DOWN" else (0.0, 0)
                speed_bytes = got
                append_row(SPEED_LOG, SPEED_HEADER,
                           [now(), mbps, st["conn"], st["network"], st["isp"]])
                print(f"{now()}  >>> download {mbps} Mbps  ({st['network']} via {st['conn']})")
                st["t_speed"] = time.time()

            st["last_status"] = status
            time.sleep(max(0, CHECK_INTERVAL_SEC - (time.time() - start)))
    finally:
        try:
            if open(PID_FILE).read().strip() == str(os.getpid()):
                os.remove(PID_FILE)
        except Exception:
            pass


# ================= background control =================
def pythonw():
    exe = sys.executable
    if IS_WIN:
        cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(cand):
            return cand
    return exe


def start_bg():
    pid = running_pid()
    if pid:
        print(f"Already running (PID {pid}).")
        return
    script = os.path.abspath(__file__)
    if IS_WIN:
        subprocess.Popen([pythonw(), script, "monitor"], cwd=BASE, close_fds=True,
                         creationflags=0x00000008 | NO_WINDOW)   # DETACHED_PROCESS
    else:
        subprocess.Popen([sys.executable, script, "monitor"], cwd=BASE,
                         stdout=open(LOG_FILE, "a"), stderr=subprocess.STDOUT,
                         start_new_session=True)
    time.sleep(3)
    pid = running_pid()
    print(f"Started in background (PID {pid})." if pid else
          f"Could not confirm start - check {LOG_FILE}")


def stop_bg():
    pid = running_pid()
    if not pid:
        print("Not running.")
        return
    if IS_WIN:
        run(["taskkill", "/PID", str(pid), "/F"])
    else:
        os.kill(pid, 15)
    try:
        os.remove(PID_FILE)
    except Exception:
        pass
    print(f"Stopped (PID {pid}).")


def startup_file():
    return os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup",
                        "NetMonitor.vbs")


def autostart(on):
    if not IS_WIN:
        print("Autostart helper is for Windows only.")
        return
    path = startup_file()
    if on:
        with open(path, "w") as f:
            f.write('CreateObject("WScript.Shell").Run """%s"" ""%s"" monitor", 0, False\n'
                    % (pythonw(), os.path.abspath(__file__)))
        print(f"Autostart ON  ({path})\nThe monitor will start silently every time you log in.")
    else:
        if os.path.exists(path):
            os.remove(path)
        print("Autostart OFF")


def status_cmd():
    pid = running_pid()
    print(f"Monitor: {'RUNNING (PID %s)' % pid if pid else 'NOT running'}")
    if IS_WIN:
        print(f"Autostart: {'ON' if os.path.exists(startup_file()) else 'OFF'}")
    rows = read_rows(NET_LOG)[-5:]
    if rows:
        print("\nLast checks:")
        for r in rows:
            print(f"  {r['time']}  [{r['status']:4}] ping={r['latency_ms'] or '---'} "
                  f"loss={r['loss_pct']}%  {r.get('network')} via {r.get('conn')}")


# ================= report =================
def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_all(pattern):
    rows = []
    for p in sorted(glob.glob(os.path.join(BASE, pattern))):
        for r in read_rows(p):
            try:
                r["t"] = datetime.strptime(r["time"], TFMT)
            except Exception:
                continue
            r["network"] = r.get("network") or "unknown (old log)"
            r["conn"] = r.get("conn") or "unknown"
            rows.append(r)
    rows.sort(key=lambda r: r["t"])
    return rows


def filter_rows(rows, network=None, hours=None, date=None):
    if network:
        n = network.lower()
        rows = [r for r in rows if n in r["network"].lower() or n in r["conn"].lower()]
    if hours:
        cut = datetime.now() - timedelta(hours=hours)
        rows = [r for r in rows if r["t"] >= cut]
    if date:
        rows = [r for r in rows if r["t"].strftime("%Y-%m-%d") == date]
    return rows


def networks_cmd():
    rows = load_all("net_log*.csv")
    if not rows:
        print("No data yet.")
        return
    seen = {}
    for r in rows:
        k = (r["network"], r["conn"])
        s = seen.setdefault(k, [0, r["t"], r["t"]])
        s[0] += 1
        s[2] = r["t"]
    print(f"{'Provider':20} {'Connection':22} {'Checks':>7}  Hours  First seen -> last seen")
    for (net, conn), (n, a, b) in sorted(seen.items(), key=lambda x: -x[1][0]):
        print(f"{net:20} {conn:22} {n:7}  {n * CHECK_INTERVAL_SEC / 3600:5.1f}  "
              f"{a:%d %b %H:%M} -> {b:%d %b %H:%M}")


def summarize(net, spd):
    total = len(net)
    down = sum(r["status"] == "DOWN" for r in net)
    bad = sum(r["status"] == "BAD" for r in net)
    lat = [v for v in (fnum(r["latency_ms"]) for r in net) if v is not None]
    loss = [fnum(r["loss_pct"]) or 0 for r in net]
    mb = [fnum(r["download_mbps"]) or 0 for r in spd]
    return {
        "checks": total, "hours": total * CHECK_INTERVAL_SEC / 3600,
        "uptime": 100 * (total - down) / total if total else 0,
        "good": 100 * (total - down - bad) / total if total else 0,
        "ping_med": statistics.median(lat) if lat else None,
        "ping_avg": sum(lat) / len(lat) if lat else None,
        "loss": sum(loss) / len(loss) if loss else 0,
        "speed_avg": sum(mb) / len(mb) if mb else None,
        "speed_max": max(mb) if mb else None, "speed_min": min(mb) if mb else None,
        "speed_n": len(mb),
    }


def fmt(v, f="{:.0f}", none="-"):
    return none if v is None else f.format(v)


def report(network=None, hours=None, date=None):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        sys.exit("Please run:  pip install matplotlib")

    net = filter_rows(load_all("net_log*.csv"), network, hours, date)
    spd = filter_rows(load_all("speed_log*.csv"), network, hours, date)
    if not net:
        sys.exit("No data for this filter. Try:  python net_monitor.py networks")

    nets = sorted({r["network"] for r in net}, key=lambda n: -sum(r["network"] == n for r in net))
    palette = ["#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#7f7f7f"]
    color = {n: palette[i % len(palette)] for i, n in enumerate(nets)}
    gap_limit = CHECK_INTERVAL_SEC * 4

    t_all = [r["t"] for r in net]
    gaps = [(a, b) for a, b in zip(t_all, t_all[1:]) if (b - a).total_seconds() > gap_limit]
    outages, cur = [], None
    for r in net:
        if cur and (r["t"] - cur[1]).total_seconds() > gap_limit:
            outages.append(cur)
            cur = None
        if r["status"] == "DOWN":
            cur = [r["t"], r["t"]] if cur is None else [cur[0], r["t"]]
        elif cur:
            outages.append(cur)
            cur = None
    if cur:
        outages.append(cur)

    def broken(times, vals, limit):
        ot, ov = [], []
        for i, (ti, v) in enumerate(zip(times, vals)):
            if i and (ti - times[i - 1]).total_seconds() > limit:
                ot.append(times[i - 1] + (ti - times[i - 1]) / 2)
                ov.append(float("nan"))
            ot.append(ti)
            ov.append(float("nan") if v is None else v)
        return ot, ov

    def shade(a):
        for s, e in outages:
            a.axvspan(s, e, color="red", alpha=0.25, lw=0)
        for s, e in gaps:
            a.axvspan(s, e, color="grey", alpha=0.15, lw=0, hatch="//")

    title = "Internet report"
    if network:
        title += f"  [filter: {network}]"
    fig, ax = plt.subplots(6, 1, figsize=(15, 26))
    fig.suptitle(f"{title}\n{t_all[0]:%d %b %H:%M}  ->  {t_all[-1]:%d %b %H:%M}",
                 fontsize=15, fontweight="bold")

    # 1 speed
    a = ax[0]
    for n in nets:
        sub = [r for r in spd if r["network"] == n]
        if sub:
            a.plot(*broken([r["t"] for r in sub], [fnum(r["download_mbps"]) for r in sub],
                           SPEED_INTERVAL_SEC * 2), marker="o", color=color[n], label=n)
    shade(a)
    a.set_ylabel("Mbps")
    a.set_title("Download speed   (red = internet down,  grey = no data)")

    # 2 ping
    a = ax[1]
    for n in nets:
        sub = [r for r in net if r["network"] == n]
        a.plot(*broken([r["t"] for r in sub], [fnum(r["latency_ms"]) for r in sub], gap_limit),
               color=color[n], lw=.8, label=n)
    a.axhline(150, color="orange", ls="--", lw=1)
    shade(a)
    a.set_ylabel("ms")
    a.set_title("Ping / latency   (orange line = 150 ms, above it feels slow)")

    # 3 loss
    a = ax[2]
    for n in nets:
        sub = [r for r in net if r["network"] == n]
        lt, lv = broken([r["t"] for r in sub], [fnum(r["loss_pct"]) or 0 for r in sub], gap_limit)
        a.fill_between(lt, [0 if v != v else v for v in lv], color=color[n], alpha=.55,
                       step="mid", where=[v == v for v in lv], label=n)
    shade(a)
    a.set_ylim(0, 105)
    a.set_ylabel("%")
    a.set_title("Packet loss")

    # 4 PC usage
    a = ax[3]
    pt, pd = broken(t_all, [fnum(r.get("pc_down_kbps")) for r in net], gap_limit)
    _, pu = broken(t_all, [fnum(r.get("pc_up_kbps")) for r in net], gap_limit)
    a.plot(pt, pd, color="#1f77b4", lw=.8, label="PC download kbps")
    a.plot(pt, pu, color="#d62728", lw=.8, label="PC upload kbps")
    a.axhline(BUSY_KBPS, color="grey", ls=":", lw=1, label=f"{BUSY_KBPS} kbps = 'busy'")
    shade(a)
    a.set_ylabel("kbps")
    a.set_title("Your PC's own internet use   (high here + bad ping = your usage;  low here + bad ping = provider)")

    for a in ax[:4]:
        a.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
        a.grid(alpha=.3)
        if a.get_legend_handles_labels()[0]:
            a.legend(loc="upper left", fontsize=8)

    # 5 & 6 hourly per network
    hours_r = list(range(24))
    w = 0.8 / max(len(nets), 1)

    def hourly(rows, key):
        out = []
        for h in hours_r:
            v = [fnum(r[key]) for r in rows if r["t"].hour == h]
            v = [x for x in v if x is not None]
            out.append(sum(v) / len(v) if v else float("nan"))
        return out

    for a, rows, key, lab in [(ax[4], spd, "download_mbps", "Avg download Mbps"),
                              (ax[5], net, "latency_ms", "Avg ping ms")]:
        for i, n in enumerate(nets):
            vals = hourly([r for r in rows if r["network"] == n], key)
            a.bar([h - 0.4 + w * (i + .5) for h in hours_r], [0 if v != v else v for v in vals],
                  width=w, color=color[n], label=n)
        a.set_xticks(hours_r)
        a.set_xlabel("Hour of day")
        a.set_ylabel(lab)
        a.grid(alpha=.3, axis="y")
        a.legend(loc="upper left", fontsize=8)
    ax[4].set_title("Which hours are FAST?  (download, higher = better)")
    ax[5].set_title("Which hours are SLOW?  (ping, lower = better)")
    ax[5].axhline(150, color="orange", ls="--", lw=1)

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(REPORT_PNG, dpi=100)

    # ---------- text summary ----------
    L = []
    L.append("=" * 78)
    L.append(f"{title}:  {t_all[0]:%Y-%m-%d %H:%M}  ->  {t_all[-1]:%Y-%m-%d %H:%M}")
    L.append("=" * 78)
    L.append(f"{'Provider':16}{'Hours':>6}{'Uptime':>8}{'Good':>7}{'Ping med':>10}"
             f"{'Loss':>7}{'Speed avg':>11}{'best':>7}{'worst':>7}")
    for n in nets:
        s = summarize([r for r in net if r["network"] == n], [r for r in spd if r["network"] == n])
        L.append(f"{n[:16]:16}{s['hours']:6.1f}{s['uptime']:7.1f}%{s['good']:6.0f}%"
                 f"{fmt(s['ping_med'], '{:.0f} ms'):>10}{s['loss']:6.1f}%"
                 f"{fmt(s['speed_avg'], '{:.2f}'):>11}{fmt(s['speed_max'], '{:.1f}'):>7}"
                 f"{fmt(s['speed_min'], '{:.1f}'):>7}")
    L.append("  Uptime = not fully down.  Good = ping < 300 ms and loss < 25 %.  Speed in Mbps.")

    # busy vs idle
    busy = [r for r in net if (fnum(r.get("pc_down_kbps")) or 0) + (fnum(r.get("pc_up_kbps")) or 0) > BUSY_KBPS]
    busy_ids = {id(r) for r in busy}
    idle = [r for r in net if r.get("pc_down_kbps") not in (None, "") and id(r) not in busy_ids]
    if busy and idle:
        sb, si = summarize(busy, []), summarize(idle, [])
        L.append("")
        L.append("When YOU were using the internet vs. PC idle:")
        L.append(f"  PC busy : {sb['checks']:5} checks  ping med {fmt(sb['ping_med'])} ms  good {sb['good']:.0f}%")
        L.append(f"  PC idle : {si['checks']:5} checks  ping med {fmt(si['ping_med'])} ms  good {si['good']:.0f}%")
        L.append("  -> If 'idle' is also bad, the problem is the provider, not your usage.")

    # best / worst hours
    for n in nets:
        sub = [r for r in net if r["network"] == n]
        hp = [(h, v) for h, v in zip(hours_r, hourly(sub, "latency_ms")) if v == v]
        if len(hp) >= 2:
            b, wst = min(hp, key=lambda x: x[1]), max(hp, key=lambda x: x[1])
            L.append(f"{n}: best hour {b[0]:02d}:00 ({b[1]:.0f} ms)   worst hour {wst[0]:02d}:00 ({wst[1]:.0f} ms)")

    # connections used
    L.append("")
    L.append("Connections used:")
    for c in sorted({(r["network"], r["conn"]) for r in net}):
        n_ = sum(1 for r in net if (r["network"], r["conn"]) == c)
        L.append(f"  {c[0]} via {c[1]}: {n_ * CHECK_INTERVAL_SEC / 3600:.1f} h")

    if gaps:
        L.append("")
        L.append(f"NO DATA periods (PC off/asleep, monitor stopped, or other network filtered out): {len(gaps)}")
        for s_, e in gaps[-15:]:
            L.append(f"  {s_:%d %b %H:%M} -> {e:%d %b %H:%M}  ({(e - s_).total_seconds() / 3600:.1f} h)")
    L.append("")
    L.append(f"Outages (internet fully down): {len(outages)}")
    for s_, e in outages[-25:]:
        mins = max(1, round((e - s_).total_seconds() / 60 + CHECK_INTERVAL_SEC / 60))
        nn = next((r["network"] for r in net if r["t"] == s_), "")
        L.append(f"  {s_:%d %b %H:%M} -> {e:%H:%M}  (~{mins} min)  {nn}")
    if len(outages) > 25:
        L.append(f"  ... showing last 25 of {len(outages)}")
    L.append("")
    L.append(f"Graph: {REPORT_PNG}")
    text = "\n".join(L)
    print(text)
    with open(SUMMARY_TXT, "w", encoding="utf-8") as f:
        f.write(text + "\n")


# ================= main =================
def arg(name, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return cast(sys.argv[i + 1])
    return None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "monitor":
        try:
            monitor()
        except KeyboardInterrupt:
            print("\nStopped.")
    elif cmd == "start":
        start_bg()
    elif cmd == "stop":
        stop_bg()
    elif cmd == "status":
        status_cmd()
    elif cmd == "autostart":
        autostart((sys.argv[2] if len(sys.argv) > 2 else "on").lower() == "on")
    elif cmd == "networks":
        networks_cmd()
    elif cmd == "report":
        report(arg("--network"), arg("--hours", float), arg("--date"))
    else:
        print(__doc__)
