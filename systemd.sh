#!/bin/bash

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SERVICE_NAME="lauretta-realtime.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

cat > "${SERVICE_PATH}" << EOF
[Unit]
Description=Lauretta Realtime Backend
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${SCRIPT_DIR}
Environment=RELOAD=1
ExecStart=/usr/bin/docker compose up -d db ingestor reid association webapp
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "${SERVICE_PATH}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl start "${SERVICE_NAME}"

echo "Waiting 10 seconds for service to initialize..."
sleep 10

echo "Service status:"
systemctl status "${SERVICE_NAME}"
