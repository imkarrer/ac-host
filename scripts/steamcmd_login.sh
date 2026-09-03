#!/bin/sh
# One-time SteamCMD login on ac-box. Run from an SSH session (not docker -d).
# Usage: sudo /var/lib/ac-host/src/scripts/steamcmd_login.sh YOUR_STEAM_USERNAME
set -eu
USER="${1:?steam username}"
export AC_STATE="${AC_STATE:-/var/lib/ac-host}"
export AC_CONTENT="${AC_CONTENT:-/var/lib/ac-host/content}"
cd /var/lib/ac-host/src
docker compose --profile build -f compose/docker-compose.yml build static
docker run -it --rm --entrypoint /bin/sh \
  -v ac-host_ac-server:/opt/ac \
  -v ac-host_steam:/home/ac/Steam \
  ac-host-server:latest \
  -c "./steamcmd.sh +@sSteamCmdForcePlatformType windows +force_install_dir /opt/ac +login \"$USER\" +app_update 302550 validate +quit"
echo
echo "If /opt/ac/acServer exists, start lobbies with: systemctl restart ac-host-static"
