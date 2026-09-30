#!/bin/bash
set -euo pipefail
umask 077
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
app_dir=$(cd "$source_dir/../.." && pwd)
test ! -L /var/lib/mulino-monitor
test ! -L /var/lib/mulino-monitor/panel
test -f /usr/local/lib/mulino-monitor/monitor.py
test -f /usr/local/lib/mulino-deploy/controller.py
/usr/local/sbin/mulino-deploy status
install -d -m 0700 /opt/mulino-panel-tools
backup=$(mktemp -d /opt/mulino-panel-tools/pre-install-v1.2.0-XXXXXXXX)
cp -a /usr/local/lib/mulino-monitor/monitor.py "$backup/monitor.py"
cp -a /usr/local/lib/mulino-deploy/controller.py "$backup/controller.py"
install -m 0644 "$app_dir/ops/monitoring/monitor.py" /usr/local/lib/mulino-monitor/monitor.py
install -m 0644 "$app_dir/ops/deploy/controller.py" /usr/local/lib/mulino-deploy/controller.py
systemctl start mulino-monitor.service
test -d /var/lib/mulino-monitor/panel
test -f /var/lib/mulino-monitor/panel/status.json
/usr/local/sbin/mulino-deploy status
echo 'Monitor e controller aggiornati; Mugnaio non riavviato.'
