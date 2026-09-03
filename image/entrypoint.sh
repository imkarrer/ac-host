#!/bin/sh
set -eu

AC_INSTALL="${AC_INSTALL:-/opt/ac}"
AC_INSTANCE="${AC_INSTANCE:-/instance}"
STEAMCMD_LOGIN="${STEAMCMD_LOGIN:-anonymous}"

# After a one-time interactive Steam login, acServer lives on the shared
# volume. Do not call steamcmd again on every lobby start (anonymous fails
# with "No subscription", and Guard codes cannot be typed in -d mode).
if [ -x "$AC_INSTALL/acServer" ] && [ "${STEAMCMD_UPDATE:-0}" != "1" ]; then
  echo "acServer already present, skipping steamcmd"
else
  cd /opt/steamcmd
  if [ "$STEAMCMD_LOGIN" = "anonymous" ]; then
    ./steamcmd.sh +@sSteamCmdForcePlatformType windows +force_install_dir "$AC_INSTALL" +login anonymous +app_update 302550 validate +quit
  else
    ./steamcmd.sh +@sSteamCmdForcePlatformType windows +force_install_dir "$AC_INSTALL" +login "$STEAMCMD_LOGIN" +app_update 302550 validate +quit
  fi
fi

# Each container gets its own cwd so two acServer processes can share the
# steam install without writing logs on top of each other.
mkdir -p "$AC_INSTANCE"
ln -sfn "$AC_INSTALL/acServer" "$AC_INSTANCE/acServer"
ln -sfn "$AC_INSTALL/system" "$AC_INSTANCE/system"
ln -sfn "${AC_CONTENT:-$AC_INSTALL/content}" "$AC_INSTANCE/content"
ln -sfn "${AC_CFG_DIR:-$AC_INSTALL/cfg}" "$AC_INSTANCE/cfg"
ln -sfn "${AC_RESULTS_DIR:-$AC_INSTALL/results}" "$AC_INSTANCE/results"

if [ ! -x "$AC_INSTALL/acServer" ]; then
  echo "acServer missing after steamcmd; check AppID 302550 download" >&2
  ls -la "$AC_INSTALL" >&2 || true
  exit 1
fi

cd "$AC_INSTANCE"
exec ./acServer
