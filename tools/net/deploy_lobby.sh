#!/usr/bin/env bash
# Installs the online lobby (ssbu_lobby.py) as a systemd service on a Linux server, e.g. an Oracle Cloud "Always Free"
# Ubuntu VM. Run it ON the server, from the folder that holds ssbu_lobby.py:
#     sudo bash deploy_lobby.sh [port]            (default UDP port 39500)
# Then players set online_server = <server address>:<port> (or SSBU_ONLINE=<server address>:<port>).
# Oracle Cloud also needs the port opened in the VCN: Networking > Virtual cloud networks > your VCN > Security List >
# Add Ingress Rule: source 0.0.0.0/0, protocol UDP, destination port <port>. This script opens the VM's own firewall.
# Standard library Python only; nothing else is installed. Remove: systemctl disable --now ssbu-lobby; rm -r /opt/ssbu-lobby
set -euo pipefail
PORT="${1:-39500}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
[ -f "$HERE/ssbu_lobby.py" ] || { echo "ssbu_lobby.py not found next to this script"; exit 1; }
command -v python3 >/dev/null || { apt-get update -q && apt-get install -y -q python3; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' || { echo "python 3.8 or newer needed"; exit 1; }

install -d -m 755 /opt/ssbu-lobby
install -m 644 "$HERE/ssbu_lobby.py" /opt/ssbu-lobby/ssbu_lobby.py

cat > /etc/systemd/system/ssbu-lobby.service <<EOF
[Unit]
Description=SSBU native port online lobby (UDP $PORT)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/ssbu-lobby/ssbu_lobby.py --bind 0.0.0.0 --port $PORT
Restart=always
RestartSec=3
DynamicUser=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
NoNewPrivileges=yes
MemoryMax=256M
CPUQuota=50%
LogRateLimitIntervalSec=60
LogRateLimitBurst=200

[Install]
WantedBy=multi-user.target
EOF

# the VM's own firewall (Oracle's Ubuntu images use iptables rules; ufw if it is active)
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow "$PORT/udp"
else
    iptables -C INPUT -p udp --dport "$PORT" -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p udp --dport "$PORT" -j ACCEPT
    if command -v netfilter-persistent >/dev/null; then netfilter-persistent save; else
        echo "note: install iptables-persistent to keep the firewall rule after a reboot"; fi
fi

systemctl daemon-reload
systemctl enable --now ssbu-lobby
sleep 1
systemctl --no-pager status ssbu-lobby | head -5
echo "lobby running on UDP $PORT. Logs: journalctl -u ssbu-lobby -f"
echo "remember the cloud firewall (Oracle: VCN Security List ingress rule, UDP $PORT)"
