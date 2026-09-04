{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.ac-host;
  portList =
    start: count:
    lib.genList (i: start + i) count;
in
{
  options.services.ac-host = {
    enable = lib.mkEnableOption "Assetto Corsa lobby host (Docker + firewall + static lobbies)";

    repoDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/ac-host/src";
      description = "Git checkout of this ac-host tree (compose, scripts, catalog).";
    };

    stateDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/ac-host";
      description = "Whitelist, generated cfg, results, and content live here.";
    };

    authOpen = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "If true, the auth sidecar allows every Steam ID (LAN smoke test).";
    };

    requiredRole = lib.mkOption {
      type = lib.types.str;
      default = "ac-practice";
      description = "Whitelist role the sidecar requires once authOpen is false.";
    };

    gamePortStart = lib.mkOption {
      type = lib.types.port;
      default = 9600;
    };

    gamePortCount = lib.mkOption {
      type = lib.types.ints.positive;
      default = 16;
    };

    httpPortStart = lib.mkOption {
      type = lib.types.port;
      default = 8081;
    };

    detailsPortStart = lib.mkOption {
      type = lib.types.port;
      default = 8181;
    };

  };

  # Optional manual dev stack (not started at boot). Same repo, isolated state + ports 8+.
  options.services.ac-host-dev = {
    enable = lib.mkEnableOption "Assetto Corsa dev/test lobby stack (manual start only)";

    stateDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/ac-host-dev";
      description = "Dev whitelist, cfg, and leaderboard (separate from production).";
    };
  };

  config = lib.mkMerge [
    (lib.mkIf cfg.enable {
    virtualisation.docker.enable = true;
    virtualisation.docker.autoPrune.enable = true;

    environment.systemPackages = [
      pkgs.docker-compose
      pkgs.python3
      pkgs.git
      pkgs.rsync
    ];

    networking.firewall.allowedTCPPorts =
      (portList cfg.gamePortStart cfg.gamePortCount)
      ++ (portList cfg.httpPortStart cfg.gamePortCount)
      ++ (portList cfg.detailsPortStart cfg.gamePortCount);

    networking.firewall.allowedUDPPorts = portList cfg.gamePortStart cfg.gamePortCount;

    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0750 root root -"
      "d ${cfg.stateDir}/content 0755 root root -"
      "d ${cfg.stateDir}/dist 0755 root root -"
      "d ${cfg.stateDir}/static 0755 root root -"
      "d ${cfg.stateDir}/races 0755 root root -"
      "d ${cfg.repoDir} 0755 root root -"
    ];

    systemd.services.ac-host-static = {
      description = "Assetto Corsa static practice lobbies";
      wantedBy = [ "multi-user.target" ];
      after = [ "docker.service" ];
      requires = [ "docker.service" ];
      path = [
        pkgs.docker
        pkgs.docker-compose
        pkgs.python3
        pkgs.coreutils
      ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        WorkingDirectory = cfg.repoDir;
        Environment = [
          "AC_STATE=${cfg.stateDir}"
          "AC_CONTENT=${cfg.stateDir}/content"
          "AUTH_OPEN=${if cfg.authOpen then "1" else "0"}"
          "AUTH_REQUIRED_ROLE=${cfg.requiredRole}"
          "COMPOSE_PROJECT_NAME=ac-host"
          "AC_ENV=prod"
        ];
        ExecStart = "${pkgs.python3}/bin/python3 ${cfg.repoDir}/scripts/acctl.py --env prod up-static";
        ExecStop = "${pkgs.python3}/bin/python3 ${cfg.repoDir}/scripts/acctl.py --env prod down-static";
      };
      # oneshot ExecStop is docker rm -f; never bounce this on nixos-rebuild
      restartIfChanged = false;
      stopIfChanged = false;
    };

    systemd.services.ac-host-dev = lib.mkIf config.services.ac-host-dev.enable {
      description = "Assetto Corsa dev/test lobby (manual — does not start at boot)";
      after = [ "docker.service" "ac-host-static.service" ];
      requires = [ "docker.service" ];
      path = [
        pkgs.docker
        pkgs.docker-compose
        pkgs.python3
        pkgs.coreutils
      ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        WorkingDirectory = cfg.repoDir;
        Environment = [
          "AC_STATE=${config.services.ac-host-dev.stateDir}"
          "AC_CONTENT=${cfg.stateDir}/content"
          "COMPOSE_PROJECT_NAME=ac-host-dev"
          "AC_ENV=dev"
        ];
        ExecStart = "${pkgs.python3}/bin/python3 ${cfg.repoDir}/scripts/acctl.py --env dev up-static";
        ExecStop = "${pkgs.python3}/bin/python3 ${cfg.repoDir}/scripts/acctl.py --env dev down-static --all";
      };
      restartIfChanged = false;
      stopIfChanged = false;
    };

    # 03:00 America/Chicago recycle so the 24h practice TIME never lands on busy hours.
    # Persistent=false: if the box was off at 3am, skip — boot already starts lobbies.
    systemd.services.ac-host-nightly = {
      description = "Assetto Corsa 03:00 practice lobby recycle";
      after = [ "docker.service" "ac-host-static.service" ];
      requires = [ "docker.service" ];
      path = [
        pkgs.docker
        pkgs.docker-compose
        pkgs.python3
        pkgs.coreutils
      ];
      serviceConfig = {
        Type = "oneshot";
        WorkingDirectory = cfg.repoDir;
        Environment = [
          "AC_STATE=${cfg.stateDir}"
          "AC_CONTENT=${cfg.stateDir}/content"
          "AUTH_OPEN=${if cfg.authOpen then "1" else "0"}"
          "AUTH_REQUIRED_ROLE=${cfg.requiredRole}"
          "COMPOSE_PROJECT_NAME=ac-host"
          "AC_ENV=prod"
          "TZ=America/Chicago"
          "AC_TZ=America/Chicago"
          "PRACTICE_RESTART_AT=03:00"
        ];
        ExecStart = "${pkgs.python3}/bin/python3 ${cfg.repoDir}/scripts/acctl.py --env prod recycle-static";
      };
      restartIfChanged = false;
      stopIfChanged = false;
    };

    systemd.timers.ac-host-nightly = {
      description = "03:00 CT practice lobby recycle";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "*-*-* 03:00:00";
        Persistent = false;
        AccuracySec = "1s";
      };
    };
    })
    (lib.mkIf config.services.ac-host-dev.enable {
      systemd.tmpfiles.rules = [
        "d ${config.services.ac-host-dev.stateDir} 0750 root root -"
        "d ${config.services.ac-host-dev.stateDir}/dist 0755 root root -"
        "d ${config.services.ac-host-dev.stateDir}/static 0755 root root -"
        "d ${config.services.ac-host-dev.stateDir}/races 0755 root root -"
      ];
    })
  ];
}
