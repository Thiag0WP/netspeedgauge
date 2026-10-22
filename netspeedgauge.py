#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NetSpeedGauge - terminal speed test with an animated speedometer.

Works with `speedtest-go` OR Ookla's official CLI (`speedtest`).
No dependencies beyond Python 3.8+.

  netspeedgauge                         auto-detects the backend
  netspeedgauge --bin ~/Downloads/speedtest-go/speedtest-go
  netspeedgauge --style signal          minimal look (signal bars + comet)
  netspeedgauge --backend go -- --multi (flags after -- go to the backend)
  netspeedgauge --demo                  every animation, fake speeds, no network
"""
import argparse, fcntl, json, math, os, pty, random, re, shutil, struct
import subprocess, sys, termios, threading, time, unicodedata

# ───────────────────────── config ─────────────────────────
SCALES = [100, 300, 500, 1000, 2000, 5000, 10000]      # Mbps
PAL = [46, 82, 118, 154, 190, 226, 220, 214, 208, 202, 196]
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
MAX_W = 76                                              # max width of the layout

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RST, BOLD = "\033[0m", "\033[1m"


def fg(n):
    return f"\033[38;5;{n}m"


GREY, MID, LGREY, WHITE, CYAN, YEL = fg(238), fg(243), fg(248), fg(231), fg(51), fg(226)


def grad_n(f):
    return PAL[min(len(PAL) - 1, max(0, int(f * (len(PAL) - 1) + 0.5)))]


def grad(f):
    return fg(grad_n(f))


def vlen(s):
    n = 0
    for ch in ANSI.sub("", s):
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def center(s, width):
    return " " * max(0, (width - vlen(s)) // 2) + s


def cell(s, width):
    """Center s inside a fixed-width cell (pads both sides)."""
    gap = max(0, width - vlen(s))
    return " " * (gap // 2) + s + " " * (gap - gap // 2)


def fmt_speed(v):
    return f"{v / 1000:.2f} Gbps" if v >= 1000 else f"{v:.1f} Mbps"


def fmt_scale(v):
    return f"{v / 1000:g} Gbps" if v >= 1000 else f"{v:g} Mbps"


def fmt_tick(v):
    return f"{v / 1000:g}G" if v >= 1000 else f"{v:g}"


def fmt_time(s):
    if s < 0.1:
        return f"{s * 1000:.0f} ms"
    if s < 1:
        return f"{s:.1f} s"
    if s < 60:
        return f"{s:.0f} s"
    if s < 3600:
        m, s = divmod(int(s), 60)
        return f"{m}m{s:02d}s"
    h, m = divmod(int(s) // 60, 60)
    return f"{h}h{m:02d}m" if h < 100 else f"{h}h"


# ───────────────────────── speed tiers & vehicles ─────────────────────────
TIERS = [  # (upper limit in Mbps, name, label)
    (10, "Snail", "<10"), (30, "Turtle", "<30"), (60, "Bicycle", "<60"),
    (150, "Car", "<150"), (400, "Bullet train", "<400"), (1000, "Rocket", "<1G"),
    (float("inf"), "Light speed", "1G+")]
N = len(TIERS)


def tier_of(v):
    return next(i for i, t in enumerate(TIERS) if v < t[0])


def tier_col(i):
    return grad_n(i / (N - 1))


# Each vehicle = drawing + shade mask, character by character:
#   M = tier's main color · D = dark shade · L = light shade · G = neutral grey (tires etc.)
VEHICLES = [
    (["   ▗▛▀▀▀▜▖  ╻ ╻",          # snail: spiral shell, light body, slime trail
      "   ▐▌ ◉ ▐▌  ▜▟▘",
      "▁▁▄▟▙▄▄▄▟▙▄▄▟▘ "],
     ["   MMMMMMM  L L",
      "   MM L MM  LLL",
      "DDLMMMMMMMLLLL "]),
    (["     ▗▄▆██▆▄▖       ",      # turtle: domed spotted shell, stretched neck
      "   ▗▟█████████▙▄▟▀▙ ",
      "    ▝▀▘    ▝▀▘  ▝▀▘ "],
     ["     MMDMMDMM       ",
      "   MMMDMMDMMDMMLLLL ",
      "    LLL    LLL  LLL "]),
    (["    __o  ",                  # classic ASCII bike; wheels spin (see draw_vehicle)
      "  _ \\<_  ",
      " (_)/(_) "],
     ["    MML  ",
      "  D MMM  ",
      " DLDMDLD "]),
    (["    ▗▄▄▄▄▄▄▖     ",          # car: roof, light windows, dark skirt
      " ▗▄▟▛▘░▐▌░▝▜▙▄▄▖ ",
      " ▝▀(◉)▀▀▀▀(◉)▀▀▘ "],
     ["    MMMMMMMM     ",
      " MMMMMLDDLMMMMMM ",
      " DDGGGDDDDGGGDDD "]),
    None,                         # bullet train: built below (it's long)
    ([" ◥▙▄▄▄▄▄▄▄▄▄▄▄▄▖  ",         # rocket: dark fins and nose, light windows
      "▐▌███ ◉  ◉  ◉ ███◣▶",
      " ◢▛▀▀▀▀▀▀▀▀▀▀▀▀▘  "],
     [" DDMMMMMMMMMMMMM  ",
      "GGMMM L  L  L MMMDD",
      " DDMMMMMMMMMMMMM  "]),
    (["       ▗▄▄▄▖       ",         # UFO: glass dome, pointed rim; lights get poetic license (RGB)
      "  ▗▄▄▄▟█░░░█▙▄▄▄▖  ",
      "◀▀◆▀▀▀◆▀▀▀◆▀▀▀◆▀▀▀▶"],
     ["       LLLLL       ",
      "  MMMMMMLLLMMMMMM  ",
      "DDMDDDMDDDMDDDMDDDD"]),
]


def _train():
    """Bullet train: streamlined tail car + middle car + locomotive, with couplers."""
    lines = ["      ▗▄▄▄▄▄▄▄▄▄▄▖ ▗▄▄▄▄▄▄▄▄▄▄▄▄▖ ▗▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▖        ",
             "  ▗▄▟███ ▀▀ ▀▀ ▀▀█▌═▐█ ▀▀ ▀▀ ▀▀ █▌═▐█ ▀▀ ▀▀ ▀▀ ▀▀ ███▙▄▄▖   ",
             " ▝▀▀▀▀▀◉▀▀▀▀▀▀◉▀▀▘ ▝▀◉▀▀▀▀▀▀▀◉▀▘ ▝▀▀◉▀▀▀◉▀▀▀◉▀▀▀◉▀▀▀▀▀▀▀▘ "]
    role = [lambda c: "M",                                               # roof
            lambda c: "L" if c == "▀" else ("G" if c == "═" else "M"),   # windows and couplers
            lambda c: "G" if c == "◉" else "D"]                          # dark base and wheels
    mask = ["".join(" " if c == " " else role[i](c) for c in ln) for i, ln in enumerate(lines)]
    return lines, mask


VEHICLES[4] = _train()

SPRITES, MASKS = [], []
for _lines, _mask in VEHICLES:
    _w = max(map(len, _lines + _mask))
    SPRITES.append([ln.ljust(_w) for ln in _lines])
    MASKS.append([m.ljust(_w, "M") for m in _mask])

# (dark, main, light) for each tier — same color family
SHADES = [(28, 46, 157), (70, 118, 193), (106, 154, 193), (178, 226, 229),
          (172, 214, 223), (166, 208, 223), (124, 196, 217)]
BARS = "▁▂▃▄▅▆▇"

# Real-world references so the number actually means something (size in bytes)
REFS = [("song", "8 MB", 8e6), ("episode", "1.5 GB", 1.5e9), ("game", "60 GB", 60e9)]


def vehicle_colors(ti, t):
    d, m, l = SHADES[ti]
    role = {"M": m, "D": d, "L": l, "G": 243}
    cols = [[role.get(ch, m) for ch in row] for row in MASKS[ti]]
    if ti == N - 1:                                    # spinning UFO lights
        blink = int(t * 6)
        lights = [k for k, ch in enumerate(SPRITES[ti][2]) if ch == "◆"]
        for j, k in enumerate(lights):
            cols[2][k] = (51, 226, 201)[(j + blink) % 3]
    return cols


def world_speed(mbps):
    """Scenery speed in cells/second. Exponent < 1: slow is truly slow,
    fast is VERY fast, but 1 Gbps is still readable."""
    return 1.5 + 4.2 * max(0.0, mbps) ** 0.45


def entry_duration(mbps):
    """Time to cross the screen into place: snail ~3 s, car ~1 s, UFO ~0.3 s."""
    return max(0.18, min(3.2, 30 / world_speed(mbps)))


def entry_ease(ti, p):
    if ti <= 1:                     # snail and turtle: crawl at a constant pace
        return p
    if ti == 2:                     # bicycle: pedals in and slows down
        return 1 - (1 - p) ** 2
    c = 1.4                         # motorized: come in hot, overshoot a bit, settle back
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


# ───────────────────────── easter egg: the ISS ─────────────────────────
ISS = ["▗▄▄▖▗▄▄▖ ▗▄▖ ▗▄▄▖▗▄▄▖",
       "▝▀▀▘▝▀▀▘═█▀█═▝▀▀▘▝▀▀▘"]
ISS_W = len(ISS[0])
ISS_CHANCE = 0.15            # chance it shows up on any given run
ISS_ORBIT = 14.0             # cells/s of its own; at light speed you overtake it


def iss_colors(t):
    cols = []
    for ln in ISS:
        row = []
        for ch in ln:
            if ch in "▗▄▖▝▀▘":
                row.append(67)              # solar panels
            elif ch == "═":
                row.append(245)             # truss
            else:
                row.append(254)             # pressurized modules
        cols.append(row)
    if int(t * 2) % 2:                      # blinking beacon
        cols[0][10] = 196
    return cols


# ───────────────────────── shared state ─────────────────────────
class State:
    def __init__(self):
        self.phase = "init"          # init | ping | download | upload | done | error
        self.target = 0.0
        self.progress = None
        self.ping = self.jitter = None
        self.server = self.isp = self.url = ""
        self.res, self.last, self.log = {}, {}, []
        self.proc = None

    def set_phase(self, ph):
        if ph != self.phase:
            self.phase, self.target, self.progress = ph, 0.0, None

    def finish(self):
        for k in ("download", "upload"):
            if k not in self.res and k in self.last:
                self.res[k] = self.last[k]
        self.set_phase("done" if self.res else "error")


# ───────────────────────── backends ─────────────────────────
def guarded(fn):
    """Make sure the test always ends (done/error), even if the backend blows up."""
    def run(binary, extra, st):
        try:
            fn(binary, extra, st)
        except Exception as e:
            st.log.append(f"internal error: {e!r}")
        finally:
            if st.phase not in ("done", "error"):
                st.finish()
    return run


def run_ookla(binary, extra, st):
    cmd = [binary, "--accept-license", "--accept-gdpr", "-f", "jsonl"] + extra
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, text=True)
    st.proc = p
    st.set_phase("ping")
    for line in p.stdout:
        try:
            j = json.loads(line)
        except ValueError:
            if line.strip():
                st.log.append(line.strip())
            continue
        if not isinstance(j, dict):
            continue
        t = j.get("type")
        if t == "testStart":
            s = j.get("server", {})
            st.server = f"{s.get('name', '')} ({s.get('location', '')})"
            st.isp = j.get("isp", "")
        elif t == "ping":
            st.set_phase("ping")
            pg = j.get("ping", {})
            st.ping, st.jitter = pg.get("latency"), pg.get("jitter")
        elif t in ("download", "upload"):
            d = j.get(t, {})
            if "bandwidth" not in d:
                continue
            st.set_phase(t)
            st.target = d["bandwidth"] * 8 / 1e6
            st.progress = d.get("progress")
            st.last[t] = st.target
        elif t == "result":
            for k in ("download", "upload"):
                bw = j.get(k, {}).get("bandwidth")
                if bw is not None:
                    st.res[k] = bw * 8 / 1e6
            pg = j.get("ping", {})
            st.ping = pg.get("latency", st.ping)
            st.jitter = pg.get("jitter", st.jitter)
            st.url = j.get("result", {}).get("url", "")
        elif t == "log":
            msg = j.get("message", "")
            if msg:
                st.log.append(f"[{j.get('level', 'log')}] {msg}")
    p.wait()
    st.finish()


# Label is case-insensitive, but the unit is not: b = bits, B = bytes.
RATE = re.compile(r"((?i:download|upload)):\s*([\d.]+)\s*([KkMmGg]?)(bps|bit/s|b/s|Bps|B/s)")
LAT = re.compile(r"Latency:\s*([\d.]+)\s*(µs|μs|us|ms|s)\b", re.I)
JIT = re.compile(r"Jitter:\s*([\d.]+)\s*(µs|μs|us|ms|s)\b", re.I)
SERVER = re.compile(r"(?:Test|Target) Server:\s*(.+)", re.I)
ISP = re.compile(r"(?:Testing From IP|ISP):\s*(.+)", re.I)
MULT = {"": 1e-6, "k": 1e-3, "m": 1.0, "g": 1e3}
TOMS = {"µs": 1e-3, "μs": 1e-3, "us": 1e-3, "ms": 1.0, "s": 1000.0}


def run_go(binary, extra, st):
    master, slave = pty.openpty()      # inside a pty, speedtest-go prints live progress
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 220, 0, 0))
    p = subprocess.Popen([binary] + extra, stdout=slave, stderr=slave,
                         stdin=subprocess.DEVNULL, close_fds=True)
    os.close(slave)
    st.proc = p
    st.set_phase("ping")

    def handle(line):
        if not line:
            return
        st.log.append(line)
        m = RATE.search(line)
        if m:
            ph = m.group(1).lower()
            v = float(m.group(2)) * MULT[m.group(3).lower()]
            if m.group(4).startswith("B"):          # bytes → bits
                v *= 8
            st.set_phase(ph)
            st.target = st.last[ph] = v
            if "used" in line.lower():
                st.res[ph] = v
            return
        if st.phase in ("init", "ping"):
            m = LAT.search(line)
            if m:
                st.ping = float(m.group(1)) * TOMS.get(m.group(2).lower(), 1.0)
            m = JIT.search(line)
            if m:
                st.jitter = float(m.group(1)) * TOMS.get(m.group(2).lower(), 1.0)
        m = SERVER.search(line)
        if m:
            st.server = m.group(1).strip()
        m = ISP.search(line)
        if m:
            st.isp = m.group(1).strip()

    buf = ""
    try:
        while True:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            buf += data.decode("utf-8", "ignore")
            parts = re.split(r"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                handle(ANSI.sub("", raw).strip())
        handle(ANSI.sub("", buf).strip())           # last line without \n
    finally:
        os.close(master)
    p.wait()
    st.finish()


# Demo: one speed per tier, all under 2 Gbps (the ISS stays a surprise)
DEMO_STEPS = [6, 20, 45, 100, 250, 650, 1500]          # Mbps
DEMO_HOLD = [4.5, 4.0, 3.5, 3.0, 3.0, 3.0, 3.5]         # seconds on each tier


def run_demo(binary, extra, st):
    """Built-in fake backend: climbs through every tier, no network needed."""
    st.server, st.isp = "Demo mode", "no network used"
    st.set_phase("ping")
    time.sleep(1.2)
    st.ping, st.jitter = 8.0, 1.0
    time.sleep(0.6)
    st.set_phase("download")
    total, done = sum(DEMO_HOLD), 0.0
    for v, hold in zip(DEMO_STEPS, DEMO_HOLD):
        t0 = time.time()
        while time.time() - t0 < hold:
            st.target = st.last["download"] = v * random.uniform(0.97, 1.02)
            st.progress = min(1.0, (done + time.time() - t0) / total)
            time.sleep(0.1)
        done += hold
    st.res["download"] = DEMO_STEPS[-1]
    st.set_phase("upload")
    t0 = time.time()
    while time.time() - t0 < 4:
        p = (time.time() - t0) / 4
        st.target = st.last["upload"] = 85 * min(1.0, p / 0.6) * random.uniform(0.97, 1.02)
        st.progress = p
        time.sleep(0.1)
    st.res["upload"] = 85.0
    st.finish()


def pick_backend(args):
    def is_ookla(path):
        try:
            r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
            return "ookla" in (r.stdout + r.stderr).lower()
        except Exception:
            return False

    if args.bin:
        if not os.path.isfile(args.bin):
            sys.exit(f"File not found: {args.bin}")
        kind = args.backend
        if kind == "auto":
            kind = "ookla" if is_ookla(args.bin) else "go"
        return kind, args.bin
    here = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~")
    go_paths = [shutil.which("speedtest-go"), os.path.join(here, "speedtest-go"),
                "./speedtest-go", f"{home}/Downloads/speedtest-go",
                f"{home}/Downloads/speedtest-go/speedtest-go"]
    go = next((p for p in go_paths if p and os.path.isfile(p) and os.access(p, os.X_OK)), None)
    ook = shutil.which("speedtest")
    if args.backend in ("auto", "ookla") and ook and is_ookla(ook):
        return "ookla", ook
    if args.backend in ("auto", "go") and go:
        return "go", go
    sys.exit("No backend found.\n"
             "  • speedtest-go: https://github.com/showwin/speedtest-go/releases\n"
             "  • or Ookla's CLI (the 'speedtest' command).\n"
             "Tip: netspeedgauge --bin /path/to/speedtest-go")


# ───────────────────────── drawing grid ─────────────────────────
class Grid:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.c = [[(" ", 0)] * w for _ in range(h)]

    def put(self, r, x, ch, col, bold=False):
        if 0 <= r < self.h and 0 <= x < self.w:
            self.c[r][x] = (ch, (col, bold))

    def sprite(self, r, x, lines, cols):
        """cols[i][k] = color of each character. Inner spaces are opaque
        (they hide whatever passes behind the sprite)."""
        for i, ln in enumerate(lines):
            if not ln.strip():
                continue
            a, b = len(ln) - len(ln.lstrip()), len(ln.rstrip())
            for k in range(a, b):
                self.put(r + i, x + k, ln[k], cols[i][k], True)

    def rows(self):
        out = []
        for row in self.c:
            s, cur = "", None
            for ch, st in row:
                if ch == " ":
                    s += ch
                    continue
                if st != cur:
                    col, bold = st
                    s += RST + (BOLD if bold else "") + fg(col)
                    cur = st
                s += ch
            out.append(s + RST)
        return out


# ───────────────────────── parallax scenery ─────────────────────────
# Layers: (depth, rows, characters, color, count per tier)
SKY_FAR = (0.05, [0], "·˙.", 236, [7] * N)
SKY_NEAR = (0.16, [1], "·✦✧", 239, [5] * N)
WIND = (1.0, [2, 3, 4, 5], "─", 244, [0, 1, 3, 5, 8, 11, 13])
GRASS = (1.8, [7], ",.'`·", 65, [10] * N)
LAYERS = [SKY_FAR, SKY_NEAR, WIND, GRASS]
SCENE_H = 8
FINALE_SPEED = 115           # cells/s of the end-of-test convoy
FINALE_GAP = 4               # space between vehicles in the convoy
FINALE_MBPS = 2000           # scenery speed during the victory lap (full warp)
FINALE_PAUSE = 0.8           # seconds showing the final result before the convoy


def streak_len(vw, L, ti):
    boost = 6 if (ti == N - 1 and L in (SKY_FAR, SKY_NEAR)) else 1     # "warp" effect
    if L is WIND:
        return max(2, int(vw * L[0] * 0.09))
    return max(1, int(vw * L[0] * 0.055 * boost))


class World:
    def __init__(self, w):
        self.w = w
        self.parts = {id(L): [] for L in LAYERS}
        self.road = 0.0

    def _spawn(self, L, anywhere):
        _, rows, chars, _, _ = L
        x = random.uniform(0, self.w) if anywhere else self.w + random.uniform(0, self.w * .4)
        return [x, random.choice(rows), random.choice(chars)]

    def step(self, dt, vw, ti):
        for L in LAYERS:
            ps = self.parts[id(L)]
            want = L[4][ti]
            while len(ps) < want:
                ps.append(self._spawn(L, anywhere=not ps or L is not WIND))
            del ps[want:]
            for i, p in enumerate(ps):
                p[0] -= vw * L[0] * dt
                if p[0] + streak_len(vw, L, ti) < 0:
                    ps[i] = self._spawn(L, anywhere=False)
        self.road += vw * 1.3 * dt

    def draw(self, g, vw, ti, fps):
        warp = ti == N - 1
        for L in LAYERS:
            base = L[3]
            ln = streak_len(vw, L, ti)
            for x, r, ch in self.parts[id(L)]:
                xi = int(x)
                if ln <= 1:
                    g.put(r, xi, ch, base)
                    continue
                # head (left, where it's going) is bright; the tail fades out
                head = tier_col(ti) if (L is WIND and ti >= 4) or (warp and L is SKY_NEAR) else 250
                for k in range(ln):
                    f = k / ln
                    col = head if f < .2 else (246 if f < .5 else (241 if f < .8 else 237))
                    c = "━" if f < .2 and ln > 3 else ("─" if f < .8 else "·")
                    g.put(r, xi + k, c, col)
        # road: dashed line; with enough motion blur the gaps close up
        shift = vw * 1.3 / fps
        pat = "━━━━━    " if shift < 1.6 else ("━━━━━━━─ " if shift < 3 else "━━━━━━━━─")
        off = int(self.road) % len(pat)
        road = (pat * (self.w // len(pat) + 3))[off:off + self.w]
        for x, ch in enumerate(road):
            if ch != " ":
                g.put(6, x, ch, 240 if ch == "━" else 237)


def base_x(ti, w):
    return w // 2 - len(SPRITES[ti][0]) // 2 + 4


def draw_vehicle(g, ti, x, t):
    spr = SPRITES[ti]
    col = tier_col(ti)
    if ti == N - 1:
        top = 2 + int(0.5 + 0.5 * math.sin(t * 4))               # UFO hovers
    else:
        top = 6 - len(spr)                                        # sits on the road
    flame = 0
    if ti == N - 1 and top == 2:                                  # tractor beam when it rises
        for k in range(6, 13):
            if random.random() < .75:
                g.put(top + 3, x + k, random.choice("░░▒"),
                      SHADES[ti][2] if k in (8, 9, 10) else SHADES[ti][0])
    if ti == 5:                                                   # gradient flame
        flame = 4 + random.randint(0, 2)
        for k in range(flame):
            f = k / flame
            ch = "▓" if f < .25 else ("▒" if f < .55 else ("░" if f < .85 else "·"))
            g.put(top + 1, x - 1 - k, ch, (226, 220, 214, 208, 202, 196)[min(5, int(f * 6))], True)
        for r in (top, top + 2):                                  # flickers on the fins
            if random.random() < .5:
                g.put(r, x, "░", random.choice((208, 214)))
    if ti >= 2:                                                   # vehicle's own trail/exhaust
        er = top + len(spr) - 1 if ti == 2 else top + 1
        ln = 2 + ti * 2 + int(1.5 * math.sin(t * 13))
        for k in range(ln):
            f = k / ln
            g.put(er, x - 1 - flame - k, "━" if f < .3 else ("─" if f < .7 else "·"),
                  (col if ti != 5 else 245) if f < .3 else (243 if f < .7 else 238))
    if ti == 2:                                                   # spinning wheel spokes
        spoke = "-\\|/"[int(t * 12) % 4]
        spr = spr[:-1] + [spr[-1].replace("_", spoke)]
    g.sprite(top, x, spr, vehicle_colors(ti, t))


class Scene:
    """Everything below the gauge: parallax, vehicles, tier changes and the ISS."""

    def __init__(self, w, now, force_iss=False):
        self.w = w
        self.world = World(w)
        self.ti = 0
        self.mbps = 0.0
        self.enter_t, self.enter_dur = now, 3.2
        self.prev_ti, self.exit_t = None, -9.0
        self.flash_t = -9.0
        lucky = force_iss or random.random() < ISS_CHANCE
        self.iss_at = now + random.uniform(5, 20) if lucky else None
        self.iss_x, self.iss_done = None, False
        self.finale_t = None                  # victory lap at the end of the test

    # ── victory lap: every vehicle in a convoy, UFO leading, snail drafting at the back ──
    def start_finale(self, now):
        if self.finale_t is None:
            self.finale_t = now

    def _convoy(self):
        """[(tier, x offset of its left edge relative to the leader's left edge)]"""
        out, off = [], 0
        for ti in range(N - 1, -1, -1):
            if out:
                off -= len(SPRITES[ti][0]) + FINALE_GAP
            out.append((ti, off))
        return out

    def _lead_x(self, now):
        return -len(SPRITES[N - 1][0]) + FINALE_SPEED * (now - self.finale_t)

    def finale_done(self, now):
        if self.finale_t is None:
            return False
        return self._lead_x(now) + self._convoy()[-1][1] > self.w + 2

    def resize(self, w):
        if w != self.w:
            self.w = w
            self.world = World(w)

    def iss_visible(self):
        return self.iss_x is not None

    def update(self, now, dt, mbps):
        if self.finale_t is not None:                     # scenery at full warp
            self.mbps = FINALE_MBPS
            vw = world_speed(FINALE_MBPS)
            self.world.step(dt, vw, N - 1)
            if self.iss_x is not None:                    # an ISS mid-pass keeps going
                self.iss_x += (ISS_ORBIT - vw * SKY_NEAR[0]) * dt
                if self.iss_x > self.w or self.iss_x < -ISS_W:
                    self.iss_x, self.iss_done = None, True
            return
        self.mbps = mbps
        nt = tier_of(mbps)
        if nt != self.ti:
            if nt > self.ti:
                self.flash_t = now
            self.prev_ti, self.exit_t = self.ti, now
            self.ti, self.enter_t = nt, now
            self.enter_dur = entry_duration(mbps)
        vw = world_speed(mbps)
        self.world.step(dt, vw, self.ti)
        # ISS: shows up if you're lucky, or always above 2 Gbps
        rel = ISS_ORBIT - vw * SKY_NEAR[0]
        if self.iss_x is None and not self.iss_done:
            if (self.iss_at is not None and now >= self.iss_at) or mbps >= 2000:
                self.iss_x = -ISS_W if rel > 0 else float(self.w)
        if self.iss_x is not None:
            self.iss_x += rel * dt
            if self.iss_x > self.w or self.iss_x < -ISS_W:
                self.iss_x, self.iss_done = None, True

    def draw(self, style, now, fps):
        g = Grid(self.w, SCENE_H)
        ti, W = self.ti, self.w
        if self.finale_t is not None:
            return self._draw_finale(g, style, now, fps)
        vw = world_speed(self.mbps)
        self.world.draw(g, vw, ti, fps)
        if self.iss_x is not None:
            g.sprite(0, int(self.iss_x), ISS, iss_colors(now))
        col = tier_col(ti)
        p = min(1.0, (now - self.enter_t) / self.enter_dur)
        e = entry_ease(ti, p)
        if style == "sprites":
            if self.prev_ti is not None:                          # previous one speeds off
                q = (now - self.exit_t) / 0.45
                if q < 1:
                    draw_vehicle(g, self.prev_ti, base_x(self.prev_ti, W) + int(q * q * W), now)
            bx = base_x(ti, W)
            x = int(round(bx - (1 - e) * (bx + len(SPRITES[ti][0]))))
            if p >= 1 and ti >= 4 and random.random() < 0.2 * (ti - 3):   # shake at high speed
                x += random.choice((-1, 1))
            draw_vehicle(g, ti, x, now)
        else:
            # comet: bright head, tail proportional to speed
            hx = W // 2 + 10
            hx = int(round(hx - (1 - e) * (hx + 2)))
            ln = min(hx - 1, 4 + ti * 5 + int(2 * math.sin(now * 11)))
            for k in range(max(0, ln)):
                f = k / ln
                g.put(4, hx - 1 - k, "━" if f < .35 else ("─" if f < .75 else "·"),
                      col if f < .35 else (245 if f < .75 else 238), f < .35)
            g.put(4, hx, "◉" if int(now * 8) % 2 else "●", col, True)
            if ti >= 3:                                           # glow around it
                g.put(3, hx, "·", 240)
                g.put(5, hx, "·", 240)
        return g.rows()

    def _draw_finale(self, g, style, now, fps):
        self.world.draw(g, world_speed(FINALE_MBPS), N - 1, fps)
        if self.iss_x is not None:
            g.sprite(0, int(self.iss_x), ISS, iss_colors(now))
        lead = self._lead_x(now)
        # draw front to back, so each vehicle sits on top of the exhaust of the one ahead
        for ti, off in self._convoy():
            x = int(lead + off)
            if style == "sprites":
                draw_vehicle(g, ti, x, now)
            else:                                         # a comet per tier, in a row
                hx = x + len(SPRITES[ti][0]) // 2
                for k in range(6):
                    g.put(4, hx - 1 - k, "━" if k < 2 else ("─" if k < 4 else "·"),
                          tier_col(ti) if k < 2 else 243)
                g.put(4, hx, "●", tier_col(ti), True)
        return g.rows()


def ladder(style, ti, cw):
    c = cw // N
    top, labels, arrow = "", "", ""
    for i, (_, _, lab) in enumerate(TIERS):
        on, cur = i <= ti, i == ti
        col = fg(tier_col(i)) if on else GREY
        if style == "sprites":
            top += cell(col + ("●" if on else "○") + RST, c)
        else:
            top += cell(col + BARS[i] * 3 + RST, c)
        labels += cell((BOLD + fg(tier_col(i)) if cur else GREY) + lab + RST, c)
        arrow += cell(fg(tier_col(i)) + "▲" + RST if cur else "", c)
    pad = " " * ((cw - c * N) // 2)
    rows = [top, labels] + ([arrow] if style == "sprites" else [])
    return [pad + r for r in rows]


# ───────────────────────── speedometer ─────────────────────────
DIG = {"0": (" _ ", "| |", "|_|"), "1": ("   ", "  |", "  |"), "2": (" _ ", " _|", "|_ "),
       "3": (" _ ", " _|", " _|"), "4": ("   ", "|_|", "  |"), "5": (" _ ", "|_ ", " _|"),
       "6": (" _ ", "|_ ", "|_|"), "7": (" _ ", "  |", "  |"), "8": (" _ ", "|_|", "|_|"),
       "9": (" _ ", "|_|", " _|"), ".": (" ", " ", "."), "-": ("   ", " _ ", "   ")}


def bigtext(txt):
    rows = ["", "", ""]
    for ch in txt:
        d = DIG.get(ch, DIG["-"])
        for i in range(3):
            rows[i] += d[i] + " "
    return rows


# Lines that aren't the gauge: header 5 + number 3 + tier 1 + gap 1 + ladder 3 + gap 1
# + scene 8 + refs 1 + footer 1
FIXED_LINES = 24


def layout(cols, rows):
    ry = max(4, min(12, rows - FIXED_LINES - 2))
    rx = min(int(ry * 2.3), max(8, (cols - 17) // 2))
    return rx, ry


def gauge_rows(rx, ry, vmax, nf):
    cx, cy = rx + 8, ry + 1
    W, H = 2 * cx + 1, ry + 2
    g = [[(" ", "")] * W for _ in range(H)]
    for k in range(0, 361):                                   # arc (two passes = thicker)
        deg = k / 2
        a = math.radians(deg)
        frac = 1 - deg / 180
        for rf in (1.0, 0.92):
            x, y = round(cx + rx * rf * math.cos(a)), round(cy - ry * rf * math.sin(a))
            g[y][x] = ("█", grad(frac)) if frac <= nf else ("░", GREY)
    for i in range(5):                                        # scale labels
        a = math.pi * (1 - i / 4)
        x = round(cx + (rx + 3) * math.cos(a))
        y = round(cy - (ry + 1) * math.sin(a))
        lab = fmt_tick(vmax * i / 4)
        x0 = x - len(lab) + 1 if i < 2 else (x - len(lab) // 2 if i == 2 else x)
        for k, ch in enumerate(lab):
            if 0 <= x0 + k < W and 0 <= y < H:
                g[y][x0 + k] = (ch, MID)
    a = math.pi * (1 - nf)                                    # needle
    col = grad(nf)
    for s in range(90):
        r = s / 90 * 0.84
        x, y = round(cx + rx * r * math.cos(a)), round(cy - ry * r * math.sin(a))
        g[y][x] = ("◆", col) if s >= 86 else ("•", WHITE)
    g[cy][cx] = ("◉", WHITE)
    return ["".join(c + ch + RST if c else ch for ch, c in row) for row in g]


# ───────────────────────── frame ─────────────────────────
def build_frame(st, v, scene, style, cols, rows, fps):
    rx, ry = layout(cols, rows)
    cw = scene.w
    lm = (cols - cw) // 2
    L = []

    def add(s="", c=True):
        L.append(" " * lm + (center(s, cw) if c else s))

    ph = st.phase
    add(f"{CYAN}{BOLD}━━ NETSPEEDGAUGE ━━{RST}")
    info = " · ".join(x for x in (st.server, st.isp) if x) or "Finding the best server…"
    add(f"{LGREY}{info[:cw - 2]}{RST}")
    add()
    order = {"init": 0, "ping": 0, "download": 1, "upload": 2, "done": 3, "error": 3}[ph]
    spin = SPIN[int(v.now * 12) % len(SPIN)]
    items = []
    for i, (key, label) in enumerate((("ping", "PING"), ("download", "▼ DOWNLOAD"), ("upload", "▲ UPLOAD"))):
        if order > i:
            val = (f"{st.ping:.0f} ms" if st.ping is not None else "") if key == "ping" \
                else (fmt_speed(st.res[key]) if key in st.res else "")
            items.append(f"{fg(46)}✔ {LGREY}{label} {fg(46)}{val}{RST}")
        elif order == i:
            items.append(f"{CYAN}{BOLD}{spin} {label}{RST}")
        else:
            items.append(f"{GREY}○ {label}{RST}")
    add("     ".join(items))
    status = {"init": "Finding server", "ping": "Measuring latency", "download": "Measuring download",
              "upload": "Measuring upload", "done": "Done", "error": "Test failed"}[ph]
    if st.progress is not None and ph in ("download", "upload"):
        n = int(24 * min(1, st.progress))
        bar = f"{CYAN}{'▰' * n}{GREY}{'▱' * (24 - n)}{RST} {st.progress * 100:3.0f}%"
    elif ph in ("done", "error"):
        bar = f"{fg(46)}{'▰' * 24}{RST}"
    else:
        p = int(v.now * 14) % 30
        bar = "".join(f"{CYAN}▰" if 0 <= k - (p - 6) < 6 else f"{GREY}▱" for k in range(24)) + RST
    add(f"{LGREY}{status:<20}{RST}{bar}  {MID}{v.elapsed:4.1f}s{RST}")

    for row in gauge_rows(rx, ry, v.scale, v.nf):                 # speedometer
        add(row)

    val = v.disp                                                  # big number
    ti = scene.ti
    tc = fg(tier_col(ti))
    txt, unit = (f"{val / 1000:.2f}", "Gbps") if val >= 1000 else (f"{val:.1f}", "Mbps")
    d = bigtext(txt)
    pad = " " * max(0, (cw - len(d[0]) - len(unit) - 2) // 2)
    for i in range(3):
        extra = f"  {LGREY}{unit}{RST}" if i == 1 else ""
        add(f"{pad}{BOLD}{tc}{d[i]}{RST}{extra}", c=False)
    name = f"{BOLD}{tc}{TIERS[ti][1].upper()}{RST}"
    if v.now - scene.flash_t < 1.4 and ti > 0:
        name += f"   {YEL}{BOLD}▲ level up{RST}"
    add(name)
    add()

    for ln in ladder(style, ti, cw):                              # tier ladder
        add(ln, c=False)
    if style != "sprites":
        add()

    for ln in scene.draw(style, v.now, fps):                      # the road
        add(ln, c=False)

    parts = []                                                    # how long would it take?
    for nm, size, b in REFS:
        tm = fmt_time(b * 8 / max(val, .01) / 1e6)
        parts.append(f"{LGREY}{nm} {GREY}{size} {RST}{BOLD}{tc}{tm}{RST}")
    add(f"{MID}at this speed:{RST}  " + f"  {GREY}·{RST}  ".join(parts))

    if scene.finale_t is not None:
        add(f"{CYAN}{BOLD}━━ victory lap ━━{RST}")
    elif scene.iss_visible():
        add(f"{fg(67)}{BOLD}✦ ISS overhead · 27,600 km/h ✦{RST}")
    elif v.now < v.flash_until:
        add(f"{YEL}{BOLD}▲ scale up: 0 – {fmt_scale(v.scale)}{RST}")
    else:
        add(f"{MID}Peak {fmt_speed(v.peak)}  ·  scale 0 – {fmt_scale(v.scale)}  ·  Ctrl+C to quit{RST}")
    return L[:rows]


class V:  # animation variables
    pass


def render_loop(st, fps, style, force_iss):
    out = sys.stdout
    v = V()
    v.disp = v.nf = v.peak = 0.0
    v.scale, si, v.flash_until = SCALES[0], 0, 0.0
    last_ph, last_size, ph_t0, done_at = None, None, time.time(), None
    last = time.time()
    scene = Scene(min(shutil.get_terminal_size((100, 30)).columns, MAX_W), last, force_iss)
    while True:
        now = time.time()
        dt = min(0.1, now - last)
        last = now
        ph = st.phase
        if ph != last_ph:
            if ph in ("download", "upload"):                      # each phase restarts at 100 Mbps
                v.disp = v.nf = v.peak = 0.0
                si, v.scale = 0, SCALES[0]
            last_ph, ph_t0 = ph, now
        tgt = st.target if ph in ("download", "upload", "done") else 0.0
        v.peak = max(v.peak, tgt)
        v.disp += (tgt - v.disp) * min(1, dt * 7)
        while si < len(SCALES) - 1 and v.disp >= SCALES[si] * 0.97:   # dynamic scale
            si += 1
            v.scale, v.flash_until = SCALES[si], now + 1.8
        v.nf += (min(1.0, v.disp / v.scale) - v.nf) * min(1, dt * 10)
        v.now, v.elapsed = now, now - ph_t0
        size = shutil.get_terminal_size((100, 30))
        if size != last_size:
            out.write("\033[2J")
            last_size = size
        scene.resize(min(size.columns, MAX_W))
        scene.update(now, dt, v.disp)
        frame = build_frame(st, v, scene, style, size.columns, size.lines, fps)
        out.write("\033[H" + "\033[K\n".join(frame) + "\033[K\033[J")
        out.flush()
        if ph in ("done", "error"):
            done_at = done_at or now
            if ph == "error" and now - done_at > 1.5:
                return
            if ph == "done":
                if now - done_at > FINALE_PAUSE:              # show the result, then the convoy
                    scene.start_finale(now)
                if scene.finale_done(now):
                    return
        time.sleep(max(0.0, 1 / fps - (time.time() - now)))


def summary(st):
    if st.phase == "error":
        print("\n✖ The test failed. Last lines from the backend:")
        for ln in st.log[-8:] or ["(the backend left no messages)"]:
            print("   ", ln)
        return
    print(f"\n{CYAN}{BOLD}━━ NETSPEEDGAUGE — results ━━{RST}\n")
    for key, icon, name in (("download", "▼", "Download"), ("upload", "▲", "Upload")):
        if key in st.res:
            v = st.res[key]
            ti = tier_of(v)
            print(f"  {BOLD}{icon} {name:<9}{fg(tier_col(ti))}{fmt_speed(v):>14}{RST}"
                  f"   {fg(tier_col(ti))}{TIERS[ti][1]}{RST}")
    if st.ping is not None:
        j = f"   jitter {st.jitter:.1f} ms" if st.jitter is not None else ""
        print(f"  {BOLD}● Ping     {RST}{st.ping:>11.1f} ms{j}")
    if st.server or st.isp:
        print(f"  {LGREY}✦ {' · '.join(x for x in (st.server, st.isp) if x)}{RST}")
    if st.url:
        print(f"  {LGREY}↗ {st.url}{RST}")
    print()


def main():
    ap = argparse.ArgumentParser(prog="netspeedgauge", description="Speed test with an animated speedometer")
    ap.add_argument("--backend", choices=["auto", "ookla", "go"], default="auto")
    ap.add_argument("--bin", help="path to speedtest-go or Ookla's speedtest")
    ap.add_argument("--style", choices=["sprites", "signal"], default="sprites",
                    help="sprites (vehicles) or signal (minimal bars + comet)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--demo", action="store_true",
                    help="show every tier's animation with fake speeds (no network, no backend)")
    ap.add_argument("--iss", action="store_true", help=argparse.SUPPRESS)   # hidden easter-egg flag
    args, extra = ap.parse_known_args()
    extra = [e for e in extra if e != "--"]
    if not sys.stdout.isatty():
        sys.exit("Run this in an interactive terminal.")
    if args.demo or os.path.basename(sys.argv[0]).endswith("demo"):      # e.g. the speeddemo link
        kind, binary = "demo", None
    else:
        kind, binary = pick_backend(args)
    st = State()
    backend = guarded({"ookla": run_ookla, "go": run_go, "demo": run_demo}[kind])
    th = threading.Thread(target=backend, args=(binary, extra, st), daemon=True)
    th.start()
    interrupted = False
    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    try:
        render_loop(st, max(5, args.fps), args.style, args.iss)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        sys.stdout.write("\033[?25h\033[?1049l" + RST)
        sys.stdout.flush()
        if st.proc and st.proc.poll() is None:
            st.proc.terminate()
    if interrupted:
        print("Test interrupted.")
    else:
        summary(st)


if __name__ == "__main__":
    main()
