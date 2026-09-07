{ config, pkgs, lib, ... }:

let
  localKeysPath = ./ssh-keys.local.nix;
  sshKeys =
    if builtins.pathExists localKeysPath then import localKeysPath else [ ];
  hardwarePath =
    if builtins.pathExists ./hardware-configuration.nix then
      ./hardware-configuration.nix
    else
      ./hardware-configuration.nix.example;
in
{
  imports = [ hardwarePath ];

  nixpkgs.config.allowUnfree = true;

  networking.hostName = "ac-box";
  networking.networkmanager.enable = true;
  time.timeZone = "America/Chicago";

  boot.loader.systemd-boot.enable = true;
  boot.loader.systemd-boot.configurationLimit = 5;
  boot.loader.efi.canTouchEfiVariables = true;
  boot.tmp.cleanOnBoot = true;

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];
  nix.settings.trusted-users = [
    "root"
    "nixosuser"
    "ac"
  ];
  nix.settings.auto-optimise-store = true;
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 7d";
  };
  nix.optimise.automatic = true;

  services.journald.extraConfig = ''
    SystemMaxUse=200M
    MaxRetentionSec=14day
  '';

  services.openssh = {
    enable = true;
    settings = {
      # Keys work for root and nixosuser. Leave password on until you confirm
      # a couple of key-only logins, then set these to false.
      PasswordAuthentication = true;
      KbdInteractiveAuthentication = true;
      PermitRootLogin = "prohibit-password";
    };
  };

  services.fail2ban.enable = true;

  hardware.graphics.enable = true;
  services.xserver.videoDrivers = [ "nvidia" ];
  hardware.nvidia = {
    modesetting.enable = true;
    powerManagement.enable = true;
    open = false;
    package = config.boot.kernelPackages.nvidiaPackages.stable;
  };

  services.ac-host = {
    enable = true;
    repoDir = "/var/lib/ac-host/src";
    stateDir = "/var/lib/ac-host";
    authOpen = false;
    requiredRole = "ac-practice";
  };

  services.ac-host-dev = {
    enable = true;
    stateDir = "/var/lib/ac-host-dev";
  };

  # Isolation only: paths + LAN rsync. Game daemons stay off until battle-test.
  # Does not change Docker or AC firewall. Rebuild must not bounce docker.service.
  services.arcade-hub = {
    enable = true;
    lanAddress = "192.168.1.50";
    gameInterface = "enp8s0";
    rsync.enable = true;
    freeciv.enable = true;
    mindustry.enable = true;
  };

  users.users.nixosuser = {
    isNormalUser = true;
    description = "Primary Server Operator";
    extraGroups = [
      "networkmanager"
      "wheel"
      "docker"
    ];
    openssh.authorizedKeys.keys = sshKeys;
  };

  users.users.ac = {
    isNormalUser = true;
    extraGroups = [
      "wheel"
      "docker"
    ];
    openssh.authorizedKeys.keys = sshKeys;
  };

  users.users.root.openssh.authorizedKeys.keys = sshKeys;

  security.sudo.wheelNeedsPassword = false;

  environment.systemPackages = [
    pkgs.htop
    pkgs.tmux
    pkgs.curl
    pkgs.rsync
    pkgs.git
  ];

  system.stateVersion = "26.05";
}
