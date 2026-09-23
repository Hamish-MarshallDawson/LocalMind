#!/usr/bin/env bash
# Install the LocalMind gateway on an always-on Debian/Proxmox machine on the same LAN as the PC.
#
#   sudo ./install.sh                # install or update
#   sudo ./install.sh --uninstall    # remove the service (keeps /var/lib/localmind-gateway)
#
# It runs as a systemd service listening on 127.0.0.1:8765 only, published to your tailnet with
# `tailscale serve`, which also tells the gateway who is asking (only LMG_ALLOWED_USERS get in).
set -euo pipefail

APP_DIR=/opt/localmind-gateway
DATA_DIR=/var/lib/localmind-gateway
ENV_FILE=/etc/localmind-gateway.env
UNIT=/etc/systemd/system/localmind-gateway.service
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ $EUID -ne 0 ]]; then echo "Run with sudo (or as root)." >&2; exit 1; fi

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl disable --now localmind-gateway 2>/dev/null || true
  rm -f "$UNIT"; systemctl daemon-reload
  tailscale serve reset 2>/dev/null || true
  echo "Removed the service. Data kept in $DATA_DIR, settings in $ENV_FILE."
  exit 0
fi

command -v python3 >/dev/null || { echo "Python 3.10+ is needed (apt-get install python3)." >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10+ is needed; this is $(python3 --version)." >&2; exit 1; }
python3 -c 'import venv' 2>/dev/null || { echo "Python's venv module is missing." >&2; exit 1; }
command -v tailscale >/dev/null || { echo "Tailscale isn't installed here: https://tailscale.com/download/linux" >&2; exit 1; }

id -u localmind-gw >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin localmind-gw
mkdir -p "$APP_DIR" "$DATA_DIR"
chown localmind-gw: "$DATA_DIR"; chmod 700 "$DATA_DIR"

rm -rf "$APP_DIR/src"; mkdir -p "$APP_DIR/src"
cp -r "$SRC_DIR/localmind_gateway" "$SRC_DIR/pyproject.toml" "$APP_DIR/src/"
# Everything goes in a private virtualenv, never the host's Python packages (on a Proxmox host
# those belong to apt). Where Debian's pip bootstrap (ensurepip, from python3-venv) is missing,
# use pip's official single-file build instead of fighting apt for it.
if python3 -c 'import ensurepip' 2>/dev/null; then
  [[ -x "$APP_DIR/venv/bin/pip" ]] || python3 -m venv "$APP_DIR/venv"
  PIP=("$APP_DIR/venv/bin/python" -m pip)
else
  [[ -x "$APP_DIR/venv/bin/python" ]] || python3 -m venv --without-pip "$APP_DIR/venv"
  if [[ ! -s "$APP_DIR/pip.pyz" ]]; then
    echo "Fetching pip (pip.pyz from bootstrap.pypa.io)…"
    python3 -c 'import sys, urllib.request; urllib.request.urlretrieve("https://bootstrap.pypa.io/pip/pip.pyz", sys.argv[1])' "$APP_DIR/pip.pyz"
  fi
  PIP=("$APP_DIR/venv/bin/python" "$APP_DIR/pip.pyz")
fi
"${PIP[@]}" install --quiet --disable-pip-version-check "$APP_DIR/src"
"$APP_DIR/venv/bin/python" -c 'import localmind_gateway.app' || { echo "The gateway didn't install correctly." >&2; exit 1; }

if [[ ! -f "$ENV_FILE" ]]; then
  read -rp "PC's MAC address for Wake-on-LAN (e.g. AA:BB:CC:DD:EE:FF): " MAC
  read -rp "LocalMind's address (e.g. https://192.168.1.50:7860): " PC_URL
  read -rp "PC's Tailscale name (e.g. my-desktop): " TS_NAME
  read -rp "Tailscale login(s) allowed to use it (e.g. you@example.com): " USERS
  [[ -n "$MAC" && -n "$PC_URL" && -n "$TS_NAME" && -n "$USERS" ]] || { echo "All four are needed." >&2; exit 1; }
  read -rsp "Gateway token (same as LOCALMIND_GATEWAY_TOKEN on the PC; blank = make one): " TOKEN; echo
  if [[ -z "$TOKEN" ]]; then TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))'); NEW_TOKEN=1; fi
  # The LAN's broadcast address, worked out from this host's own LAN address (ip doesn't always
  # print a "brd"). Tailscale's 100.x address and anything else non-private is skipped.
  BROADCAST=$(ip -4 -o addr show scope global | awk '{print $4}' | python3 -c '
import ipaddress, sys
for line in sys.stdin:
    net = ipaddress.ip_interface(line.strip()).network
    if net.is_private and net.prefixlen < 31:
        print(net.broadcast_address); break
else:
    print("255.255.255.255")')
  umask 077
  cat > "$ENV_FILE" <<EOF
# LocalMind gateway settings. Restart after editing:  systemctl restart localmind-gateway
LMG_PC_URL=$PC_URL
LMG_PC_UI_URL=$PC_URL
LMG_PC_MAC=$MAC
LMG_WOL_BROADCAST=$BROADCAST
LMG_PC_TAILSCALE_NAME=$TS_NAME
LMG_ALLOWED_USERS=$USERS
LOCALMIND_GATEWAY_TOKEN=$TOKEN
LMG_DATA_DIR=$DATA_DIR
LMG_HOST=127.0.0.1
LMG_PORT=8765
EOF
  chmod 600 "$ENV_FILE"
  if [[ -n "${NEW_TOKEN:-}" ]]; then
    echo; echo "Made a gateway token. Set the same value on the PC (PowerShell):"
    echo "  [Environment]::SetEnvironmentVariable('LOCALMIND_GATEWAY_TOKEN', '$TOKEN', 'User')"; echo
  fi
fi

cat > "$UNIT" <<EOF
[Unit]
Description=LocalMind gateway (wakes the PC, keeps chats and status while it's off)
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=localmind-gw
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/python -m localmind_gateway
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now localmind-gateway
systemctl restart localmind-gateway

# Publish on the tailnet. HTTPS needs "HTTPS certificates" enabled in the Tailscale admin console
# (DNS page); it's what lets phones install the page as an app. Plain HTTP works without it.
# Without certificates enabled, `tailscale serve --https` stops to ask for them, so check first.
CERTS=$(tailscale status --json | python3 -c 'import json,sys; print(bool(json.load(sys.stdin).get("CertDomains")))')
if [[ $CERTS == True ]] && timeout 30 tailscale serve --bg --https=443 http://127.0.0.1:8765 >/dev/null 2>&1; then
  SCHEME=https
else
  timeout 30 tailscale serve --bg --http=80 http://127.0.0.1:8765 >/dev/null
  SCHEME=http
fi
NAME=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
echo
echo "LocalMind gateway is running: $SCHEME://$NAME"
echo "On the PC, point LocalMind at it (PowerShell), then restart LocalMind:"
echo "  [Environment]::SetEnvironmentVariable('LOCALMIND_GATEWAY_URL', '$SCHEME://$NAME', 'User')"
[[ $SCHEME == http ]] && echo "(Enable HTTPS certificates in the Tailscale admin console, then re-run this, to install it as an app.)"
