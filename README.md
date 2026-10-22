# NetSpeedGauge

An internet speed test for your terminal, with an animated speedometer and a
little parallax road where your connection is drawn as a vehicle: the faster
the link, the faster the ride.

Pure Python 3.8+, no dependencies. The actual measurement is done by
[speedtest-go](https://github.com/showwin/speedtest-go) or
[Ookla's Speedtest CLI](https://www.speedtest.net/apps/cli); NetSpeedGauge
just makes it fun to watch.

```
                            ━━ NETSPEEDGAUGE ━━
             Sao Paulo (Example Networks) · Fake Fiber Telecom

                ✔ PING 8 ms     ⠏ ▼ DOWNLOAD     ○ ▲ UPLOAD
          Measuring download  ▰▰▰▰▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱  62%   6.2s
                                    150
                               █████████████
                           █████████████████████
                     75 ██████               ██████ 225
                      █████                     █████
                     ████                       •◆█░░░
                    ███                      ••••   ░░░
                   ███                    ••••       ░░░
                   ███                 ••••          ░░░
                0  ██                ◉••              ░░  300
                           _             _
                           _| |_|   |    _|   Mbps
                          |_    |   | .  _|
                                BULLET TRAIN

       ●         ●         ●         ●         ●         ○         ○
      <10       <30       <60       <150      <400      <1G       1G+
                                               ▲
     ·                         ·   .             ˙·                      ·
   ✦                                        ✧                            ·
                  ━─── ━━───
                  ▗▄▄▄▄▄▄▄▄▄▄▖ ▗▄▄▄▄▄▄▄▄▄▄▄▄▖ ▗▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▖
 ···────━━━━  ▗▄▟███ ▀▀ ▀▀ ▀▀█▌═▐█ ▀▀ ▀▀ ▀▀ █▌═▐█ ▀▀ ▀▀ ▀▀ ▀▀ ███▙▄▄▖
            ━▝▀▀▀▀▀◉▀▀▀▀▀▀◉▀▀▘ ▝▀◉▀▀▀▀▀▀▀◉▀▘ ▝▀▀◉▀▀▀◉▀▀▀◉▀▀▀◉▀▀▀▀▀▀▀▘
 ━━━━━━━─ ━━━━━━━─ ━━━━━━━─ ━━━━━━━─ ━━━━━━━─ ━━━━━━━─ ━━━━━━━─ ━━━━━━━─ ━━━
     ━───·─·                                        ━───··  ━───· ━───·
at this speed:  song 8 MB 0.3 s  ·  episode 1.5 GB 50 s  ·  game 60 GB 33m09s
         Peak 248.9 Mbps  ·  scale 0 – 300 Mbps  ·  Ctrl+C to quit
```

In a real terminal it's all in color and moving at ~30 fps.

## Requirements

- **Python 3.8+** (standard library only) on Linux or macOS.
- A terminal with 256 colors and a font that has block and box-drawing
  characters (pretty much any modern terminal).
- **One** of these backends, installed by you:
  - **speedtest-go** (open source, MIT):
    download a binary from the
    [releases page](https://github.com/showwin/speedtest-go/releases), or
    see the [project README](https://github.com/showwin/speedtest-go#installation)
    for other install options.
  - **Ookla's Speedtest CLI** (the official `speedtest` command):
    see the [install instructions](https://www.speedtest.net/apps/cli).
    Note that it's proprietary; see the [Ookla backend](#a-note-on-the-ookla-backend) section below.

Neither backend is bundled with this repository.

## Installation

```sh
git clone https://github.com/<your-user>/netspeedgauge.git
cd netspeedgauge
./install.sh
```

Then just run `speed`, or `speeddemo` to see every animation without running
a real test.

The installer:

- checks for Python 3.8+;
- links `netspeedgauge.py` as `~/.local/bin/speed` and `~/.local/bin/speeddemo`
  (it refuses to overwrite files that aren't its own);
- if no backend is installed, downloads the latest
  [speedtest-go release](https://github.com/showwin/speedtest-go/releases) for
  your OS and CPU into `~/.local/bin`, after verifying its SHA-256 checksum.
  Ookla's CLI is never downloaded automatically;
- tells you what to add to your shell config if `~/.local/bin` isn't in your `PATH`.

Since the command is a link to the cloned folder, `git pull` is all it takes to
update. Keep the folder where it is.

| Installer option | Description |
|------------------|-------------|
| `--name NAME` | Install the commands under another name: `NAME` and `NAMEdemo` (default `speed`). |
| `--no-backend` | Don't download speedtest-go. |
| `--uninstall` | Remove both commands (speedtest-go is left in place). |
| `BIN_DIR=...` | Environment variable: install somewhere other than `~/.local/bin`. |

You can also skip the installer and run `./netspeedgauge.py` directly.

## Usage

```sh
speed                                   # auto-detect the backend
speed --bin ~/Downloads/speedtest-go    # use a specific binary
speed --style signal                    # minimal look
speed --backend go -- --multi           # extra flags go to the backend
speeddemo                               # show every animation (no network)
```

When the test ends you get a short summary printed in the terminal.
Press `Ctrl+C` at any time to quit.

### Demo

`speeddemo` (same as `speed --demo`) plays every animation with made-up
speeds: it climbs through all seven tiers, from the snail to light speed, then
runs a short upload and the end-of-test victory lap. It takes about 35 seconds,
uses no network and doesn't need a backend. It works with the other options too,
e.g. `speeddemo --style signal`.

### Options

| Flag | Description |
|------|-------------|
| `--bin PATH` | Path to the backend binary (speedtest-go or Ookla's `speedtest`). The type is detected automatically unless you also pass `--backend`. |
| `--backend {auto,ookla,go}` | Which backend to use. `auto` (default) prefers Ookla's `speedtest` if it's in your `PATH`, then looks for `speedtest-go` in your `PATH`, next to the script, in the current directory and in `~/Downloads`. |
| `--style {sprites,signal}` | `sprites` (default): vehicles on a road. `signal`: signal bars and a comet. |
| `--fps N` | Animation frame rate (default 30, minimum 5). |
| `--demo` | Show every animation with fake speeds instead of running a test (what `speeddemo` does). |
| `-- ARGS...` | Everything after `--` is passed straight to the backend, e.g. `-- --multi` for speedtest-go or `-- --server-id 1234` for Ookla. |

### Speed tiers

Your current speed decides which vehicle is on the road:

| Speed | Tier |
|-------|------|
| < 10 Mbps | Snail |
| < 30 Mbps | Turtle |
| < 60 Mbps | Bicycle |
| < 150 Mbps | Car |
| < 400 Mbps | Bullet train |
| < 1 Gbps | Rocket |
| 1 Gbps and up | Light speed |

## A note on the Ookla backend

When NetSpeedGauge runs Ookla's Speedtest CLI it passes `--accept-license`
and `--accept-gdpr`, so the CLI doesn't stop to ask interactively.
**Using NetSpeedGauge with the Ookla backend therefore means you accept
Ookla's [Terms of Use](https://www.speedtest.net/about/terms) and
[Privacy Policy](https://www.speedtest.net/about/privacy).** If you don't want
to, use the speedtest-go backend (`--backend go`).

The Ookla CLI is proprietary software and is not redistributed here.

## Development

`dev/fake-speedtest-go` imitates speedtest-go's output, so you can work on the
UI without a network connection or a real backend:

```sh
./netspeedgauge.py --bin dev/fake-speedtest-go
./netspeedgauge.py --bin dev/fake-speedtest-go -- --down 2500 --up 900 --secs 4
```

## License

NetSpeedGauge is released under the [MIT License](LICENSE).

speedtest-go and Ookla's Speedtest CLI are separate projects with their own
licenses; they are not part of this repository.
