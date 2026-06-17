#!/usr/bin/env bash
set -e

# The vnc_Startup.sh script has a keepalive loop similar to the one in
# our custom_startup.sh script. The loop has a typo though, mistakenly
# referencing "custom_script" instead of "custom_startup".
# There is a stale pull request to fix this in the KASM repo,
# but until they release a new version, we can fix it like this:
sed -i 's/custom_script/custom_startup/' "$STARTUPDIR/vnc_startup.sh"

# The KASM core image has removed the following applets without removing
# their autostart entries. This remedies that.
rm -f /etc/xdg/autostart/nm-applet.desktop
rm -f /etc/xdg/autostart/print-applet.desktop