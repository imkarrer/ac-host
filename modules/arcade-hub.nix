# Canonical arcade hub module. Game files stay on /srv/arcade, not in git.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.arcade-hub;
in
{
  options.services.arcade-hub = {
    enable = lib.mkEnableOption ''
      Home-arcade hub on ac-box. Paths, LAN firewall, and rsync export only
      unless individual game services are enabled. Does not touch Docker or
      the Assetto Corsa lobby stack.
    '';

    lanAddress = lib.mkOption {
      type = lib.types.str;
      description = ''
        Game/LAN address arcade services bind to. Not 0.0.0.0.

        No default on purpose: this is a host fact, not a tenant fact — on
        ac-box it is `config.homelab.host.networks.lan.address` in the
        platform layer. A hardcoded default here is exactly how it drifted
        (this module and agent-hub each carried their own copy of the same
        IP). The composing host config must set it explicitly, e.g.
        `services.arcade-hub.lanAddress =
        config.homelab.host.networks.lan.address;`. This module stays
        importable standalone; it just refuses to guess a LAN address for
        you.
      '';
    };

    gameInterface = lib.mkOption {
      type = lib.types.str;
      description = ''
        LAN NIC. Arcade ports open on this interface only.

        No default for the same reason as lanAddress: it is
        `config.homelab.host.networks.lan.interface` on the platform side,
        owned once there and passed in, not redeclared per tenant.
      '';
    };

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = "/srv/arcade";
      description = "Library: roms, metadata, shaders, saves. Never AC content.";
    };

    stateDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/arcade";
      description = "Hub state: lobby DB, Minetest world, secrets. Not /var/lib/ac-host.";
    };

    rsync.enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Optional rsyncd. Windows spokes use SMB; Nix stations can still rsync.";
    };

    smb.enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "LAN SMB share of /srv/arcade. Windows spokes robocopy this; no WSL.";
    };

    lobby.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "arcade-lobby HTTP (not implemented in this skeleton).";
    };

    lobby.port = lib.mkOption {
      type = lib.types.port;
      default = 8090;
    };

    mitm.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "RetroArch netplay MITM (not started until battle-test netplay).";
    };

    mitm.port = lib.mkOption {
      type = lib.types.port;
      default = 55435;
    };

    minetest.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
    };

    minetest.port = lib.mkOption {
      type = lib.types.port;
      default = 30000;
    };

    mumble.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
    };

    mumble.port = lib.mkOption {
      type = lib.types.port;
      default = 64738;
    };

    freeciv.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Dedicated Freeciv server, LAN bind only. No metaserver.";
    };

    freeciv.port = lib.mkOption {
      type = lib.types.port;
      default = 5556;
    };

    mindustry.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Dedicated Mindustry server, LAN firewall only.";
    };

    mindustry.port = lib.mkOption {
      type = lib.types.port;
      default = 6567;
    };
  };

  config = lib.mkIf cfg.enable {
    users.groups.arcade = { };
    users.users.arcade = {
      isSystemUser = true;
      group = "arcade";
      home = cfg.stateDir;
      createHome = true;
    };

    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir} 0755 arcade arcade -"
      "d ${cfg.dataDir}/roms 0755 arcade arcade -"
      "d ${cfg.dataDir}/roms/snes 0755 arcade arcade -"
      "d ${cfg.dataDir}/roms/n64 0755 arcade arcade -"
      "d ${cfg.dataDir}/roms/genesis 0755 arcade arcade -"
      "d ${cfg.dataDir}/roms/dos 0755 arcade arcade -"
      "d ${cfg.dataDir}/metadata 0755 arcade arcade -"
      "d ${cfg.dataDir}/metadata/crops 0755 arcade arcade -"
      "d ${cfg.dataDir}/shaders 0755 arcade arcade -"
      "d ${cfg.dataDir}/saves 0775 arcade arcade -"
      "d ${cfg.stateDir} 0750 arcade arcade -"
      "d ${cfg.stateDir}/secrets 0700 arcade arcade -"
      "d ${cfg.stateDir}/freeciv 0750 arcade arcade -"
      "d ${cfg.stateDir}/mindustry 0750 arcade arcade -"
      "d ${cfg.dataDir}/apps 0755 arcade arcade -"
      "d ${cfg.dataDir}/apps/windows 0755 arcade arcade -"
    ];

    # Interface-scoped only. Never global allowedTCPPorts — those hit every NIC
    # including a future management link. Do not UniFi-forward these.
    networking.firewall.interfaces.${cfg.gameInterface} = {
      allowedTCPPorts =
        (lib.optional cfg.rsync.enable 873)
        ++ (lib.optionals cfg.smb.enable [ 139 445 ])
        ++ (lib.optional cfg.lobby.enable cfg.lobby.port)
        ++ (lib.optional cfg.mitm.enable cfg.mitm.port)
        ++ (lib.optional cfg.minetest.enable cfg.minetest.port)
        ++ (lib.optional cfg.mumble.enable cfg.mumble.port)
        ++ (lib.optional cfg.freeciv.enable cfg.freeciv.port)
        ++ (lib.optional cfg.mindustry.enable cfg.mindustry.port);
      allowedUDPPorts =
        (lib.optional cfg.mitm.enable cfg.mitm.port)
        ++ (lib.optional cfg.minetest.enable cfg.minetest.port)
        ++ (lib.optional cfg.mumble.enable cfg.mumble.port)
        ++ (lib.optional cfg.freeciv.enable cfg.freeciv.port)
        ++ (lib.optional cfg.mindustry.enable cfg.mindustry.port);
    };

    services.samba = lib.mkIf cfg.smb.enable {
      enable = true;
      openFirewall = false;
      nmbd.enable = false;
      settings = {
        global = {
          "workgroup" = "WORKGROUP";
          "server string" = "arcade";
          "interfaces" = "${cfg.lanAddress}/24";
          "bind interfaces only" = "yes";
          "security" = "user";
          "map to guest" = "Bad User";
          "guest account" = "arcade";
          "hosts allow" = "192.168.1. 127.0.0.1";
          "hosts deny" = "0.0.0.0/0";
        };
        arcade = {
          path = cfg.dataDir;
          "browseable" = "yes";
          "read only" = "yes";
          "guest ok" = "yes";
          "force user" = "arcade";
          "force group" = "arcade";
        };
      };
    };

    # Win10/11 Pro refuse guest SMB. Keep a real samba user; password lives
    # only in /var/lib/arcade/secrets/smb-password (not in git).
    systemd.services.arcade-smb-password = lib.mkIf cfg.smb.enable {
      description = "Ensure Samba password for arcade user";
      after = [ "samba-smbd.service" ];
      wants = [ "samba-smbd.service" ];
      wantedBy = [ "multi-user.target" ];
      path = [
        pkgs.samba
        pkgs.openssl
      ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        set -euo pipefail
        secret=${cfg.stateDir}/secrets/smb-password
        umask 077
        mkdir -p ${cfg.stateDir}/secrets
        [ -s "$secret" ] || openssl rand -hex 8 > "$secret"
        chown arcade:arcade "$secret"
        chmod 600 "$secret"
        pass=$(tr -d '\n' < "$secret")
        printf '%s\n%s\n' "$pass" "$pass" | smbpasswd -a -s arcade
      '';
    };

    services.rsyncd = lib.mkIf cfg.rsync.enable {
      enable = true;
      socketActivated = false;
      settings = {
        globalSection = {
          address = cfg.lanAddress;
          "use chroot" = true;
          "max connections" = 8;
        };
        sections = {
          arcade-lib = {
            path = cfg.dataDir;
            comment = "Arcade library (read-only: roms, metadata, shaders)";
            "read only" = true;
            uid = "arcade";
            gid = "arcade";
          };
          arcade-saves = {
            path = "${cfg.dataDir}/saves";
            comment = "Arcade profile saves (read-write)";
            "read only" = false;
            uid = "arcade";
            gid = "arcade";
          };
        };
      };
    };

    systemd.services.arcade-freeciv = lib.mkIf cfg.freeciv.enable {
      description = "Arcade Freeciv dedicated server (LAN only)";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        User = "arcade";
        Group = "arcade";
        WorkingDirectory = "${cfg.stateDir}/freeciv";
        ExecStart = "${pkgs.freeciv}/bin/freeciv-server --bind ${cfg.lanAddress} --port ${toString cfg.freeciv.port} --saves ${cfg.stateDir}/freeciv --log ${cfg.stateDir}/freeciv/server.log";
        Restart = "on-failure";
        RestartSec = 5;
      };
    };

    systemd.services.arcade-mindustry = lib.mkIf cfg.mindustry.enable {
      description = "Arcade Mindustry dedicated server (LAN only)";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        User = "arcade";
        Group = "arcade";
        WorkingDirectory = "${cfg.stateDir}/mindustry";
        ExecStart = "${pkgs.writeShellScript "arcade-mindustry" ''
          printf '%s\n' "config name Arcade" "host sandbox" | exec ${pkgs.jre_headless}/bin/java -Xms256M -Xmx1G -jar ${cfg.stateDir}/mindustry/server-release.jar
        ''}";
        Restart = "on-failure";
        RestartSec = 5;
      };
    };

    assertions = [
      {
        assertion = cfg.lanAddress != "0.0.0.0";
        message = "services.arcade-hub.lanAddress must be the LAN IP, not 0.0.0.0.";
      }
    ];
  };
}
