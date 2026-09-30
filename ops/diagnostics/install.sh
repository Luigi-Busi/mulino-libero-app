#!/bin/bash
set -euo pipefail
umask 077
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
app_dir=$(cd "$source_dir/../.." && pwd)
test -x /usr/bin/docker
test ! -L /usr/local/lib/mulino-browser-diagnostics
test ! -L /var/log/mulino-browser-diagnostics
test ! -e /etc/systemd/system/mulino-browser-diagnostics.service
install -d -m 0755 /usr/local/lib/mulino-browser-diagnostics
install -d -m 0700 /var/log/mulino-browser-diagnostics
install -m 0644 "$app_dir/browser_diagnostics.py" /usr/local/lib/mulino-browser-diagnostics/browser_diagnostics.py
install -m 0644 "$source_dir/collector.py" /usr/local/lib/mulino-browser-diagnostics/collector.py
install -m 0644 "$source_dir/mulino-browser-diagnostics.service" /etc/systemd/system/mulino-browser-diagnostics.service
systemd-analyze verify /etc/systemd/system/mulino-browser-diagnostics.service
systemctl daemon-reload
systemctl enable --now mulino-browser-diagnostics.service
systemctl is-active --quiet mulino-browser-diagnostics.service
