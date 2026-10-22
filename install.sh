#!/bin/sh
# NetSpeedGauge installer.
#
#   ./install.sh                 install 'speed' and 'speeddemo' (+ speedtest-go if no backend is found)
#   ./install.sh --name gauge    use other command names ('gauge' and 'gaugedemo')
#   ./install.sh --no-backend    never download speedtest-go
#   ./install.sh --uninstall     remove the commands
#
# BIN_DIR (default ~/.local/bin) sets where the command goes.
set -eu

NAME=speed
BIN_DIR=${BIN_DIR:-"$HOME/.local/bin"}
GET_BACKEND=1
UNINSTALL=0
REPO_URL=https://github.com/showwin/speedtest-go

while [ $# -gt 0 ]; do
    case "$1" in
        --name) [ $# -ge 2 ] || { echo "--name needs a value" >&2; exit 2; }; NAME=$2; shift ;;
        --no-backend) GET_BACKEND=0 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

HERE=$(cd "$(dirname "$0")" && pwd -P)
SCRIPT="$HERE/netspeedgauge.py"
LINKS="$BIN_DIR/$NAME $BIN_DIR/${NAME}demo"     # the script runs the demo when called as *demo
[ -f "$SCRIPT" ] || die "netspeedgauge.py not found next to install.sh"
case "$NAME" in *demo|*/*|"") die "Invalid command name: '$NAME'" ;; esac

points_to_us() {
    [ -L "$1" ] && [ "$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1")" = "$SCRIPT" ]
}

# ── uninstall ──
if [ "$UNINSTALL" = 1 ]; then
    for LINK in $LINKS; do
        if points_to_us "$LINK"; then
            rm -f "$LINK"
            say "Removed $LINK"
        else
            warn "$LINK is not a NetSpeedGauge link; left alone"
        fi
    done
    [ -x "$BIN_DIR/speedtest-go" ] && echo "    speedtest-go was left in place: rm \"$BIN_DIR/speedtest-go\" to remove it"
    exit 0
fi

# ── Python ──
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.8 or newer."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' \
    || die "Python 3.8+ is required (found $(python3 -V 2>&1))."
say "Python: $(python3 -V 2>&1)"

# ── the command ──
mkdir -p "$BIN_DIR"
chmod +x "$SCRIPT"
for LINK in $LINKS; do                         # check both before creating either
    if { [ -e "$LINK" ] || [ -L "$LINK" ]; } && ! points_to_us "$LINK"; then
        die "$LINK already exists and isn't ours. Pick another name: ./install.sh --name <name>"
    fi
done
for LINK in $LINKS; do
    if [ ! -L "$LINK" ]; then
        other=$(command -v "$(basename "$LINK")" 2>/dev/null || true)
        [ -n "$other" ] && warn "'$(basename "$LINK")' already exists at $other; it may shadow (or be shadowed by) this one"
        ln -s "$SCRIPT" "$LINK"
    fi
    say "Command: $LINK -> $SCRIPT"
done

# ── backend ──
have_backend() {
    command -v speedtest-go >/dev/null 2>&1 && return 0
    [ -x "$BIN_DIR/speedtest-go" ] && return 0
    command -v speedtest >/dev/null 2>&1 && speedtest --version 2>&1 | grep -qi ookla && return 0
    return 1
}

fetch() {  # fetch URL FILE
    if command -v curl >/dev/null 2>&1; then curl -fsSL -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
    else die "Need curl or wget to download speedtest-go"; fi
}

latest_tag() {  # follows the /releases/latest redirect (no API rate limit)
    if command -v curl >/dev/null 2>&1; then
        curl -fsSLI -o /dev/null -w '%{url_effective}' "$REPO_URL/releases/latest"
    else
        wget -S --spider "$REPO_URL/releases/latest" 2>&1 | sed -n 's/^ *[Ll]ocation: *//p' | tail -n 1
    fi | sed 's#.*/tag/##' | tr -d '\r'
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

install_speedtest_go() {
    case "$(uname -s)" in
        Linux) os=Linux ;; Darwin) os=Darwin ;; FreeBSD) os=Freebsd ;; OpenBSD) os=OpenBSD ;;
        *) warn "No speedtest-go build for $(uname -s)"; return 1 ;;
    esac
    case "$(uname -m)" in
        x86_64|amd64) arch=x86_64 ;; aarch64|arm64) arch=arm64 ;;
        armv7*) arch=armv7 ;; armv6*) arch=armv6 ;; i?86) arch=i386 ;;
        riscv64) arch=riscv64 ;;
        *) warn "No speedtest-go build for $(uname -m)"; return 1 ;;
    esac
    tag=$(latest_tag)
    case "$tag" in v[0-9]*) ;; *) warn "Couldn't find the latest speedtest-go release"; return 1 ;; esac
    file="speedtest-go_${tag#v}_${os}_${arch}.tar.gz"
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    say "Downloading speedtest-go $tag ($os/$arch)"
    fetch "$REPO_URL/releases/download/$tag/$file" "$tmp/$file" || { warn "Download failed"; return 1; }
    fetch "$REPO_URL/releases/download/$tag/checksums.txt" "$tmp/checksums.txt" || { warn "Download failed"; return 1; }
    want=$(awk -v f="$file" '$2 == f { print $1 }' "$tmp/checksums.txt")
    [ -n "$want" ] && [ "$want" = "$(sha256 "$tmp/$file")" ] || { warn "Checksum mismatch, not installing"; return 1; }
    tar -xzf "$tmp/$file" -C "$tmp" speedtest-go || { warn "Unexpected archive layout"; return 1; }
    cp "$tmp/speedtest-go" "$BIN_DIR/speedtest-go"
    chmod 755 "$BIN_DIR/speedtest-go"
    say "Backend: $BIN_DIR/speedtest-go (checksum OK)"
}

if have_backend; then
    say "Backend: already installed"
elif [ "$GET_BACKEND" = 1 ]; then
    install_speedtest_go || warn "Install a backend yourself: $REPO_URL/releases or https://www.speedtest.net/apps/cli"
else
    warn "No backend found. Install speedtest-go ($REPO_URL/releases) or Ookla's CLI (https://www.speedtest.net/apps/cli)"
fi

# ── PATH ──
case ":$PATH:" in
    *":$BIN_DIR:"*) say "Done! Run: $NAME (or ${NAME}demo to see every animation)" ;;
    *) warn "$BIN_DIR is not in your PATH. Add this to your shell config (~/.bashrc, ~/.zshrc):"
       echo "    export PATH=\"$BIN_DIR:\$PATH\""
       say "Then open a new terminal and run: $NAME" ;;
esac
