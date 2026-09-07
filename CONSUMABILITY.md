# Consumability report: ac-host modules vs. homelab/modules/platform

Scope: for each of `modules/ac-host.nix`, `modules/monitoring.nix`, and
`modules/arcade-hub.nix`, every top-level option path it sets in `config`
(not under its own `options.services.*` namespace) that is also set by one of
`/home/nixos/src/homelab/modules/platform/{boot,docker,host-options,identity,
network,nix,ssh}.nix`.

`host-options.nix` only declares `options.homelab.host.*` — it sets no
`config`, so it cannot collide with anything and is not listed as a source
below.

## modules/ac-host.nix

| Option | ac-host.nix sets | platform module sets | Verdict |
| --- | --- | --- | --- |
| `virtualisation.docker.enable` | `true` (literal, under `services.ac-host.enable`) | `anyTenantNeedsDocker` — computed from `config.homelab.tenants.*.needsDocker` (`docker.nix`) | **Conflicting-definition risk.** Both are plain `mkOption bool` definitions at equal (default) priority. NixOS only errors when the two values actually differ (verified: two equal-valued definitions merge silently; two unequal ones throw "The option \`foo' has conflicting definition values"). Composing `ac-host.nix` as-is alongside `docker.nix` works *only* as long as `anyTenantNeedsDocker` also happens to evaluate `true` — i.e. only once `assetto` is registered in `homelab.tenants` with `needsDocker = true`. Compose them before that bridge exists (tenant schema empty or assetto not yet migrated in) and `anyTenantNeedsDocker` is `false` while `ac-host.nix` still says `true`: hard eval error. This is the exact scenario `docker.nix`'s own header comment describes as "THE ONE DELIBERATE MOVE" — the fix is to delete these two lines from `ac-host.nix` once assetto is wired into the tenant schema, not to reconcile values by hand. |
| `virtualisation.docker.autoPrune.enable` | `true` (literal, same block) | same `anyTenantNeedsDocker` (`docker.nix`) | Same risk, same fix, same commit as the line above — they're set together. |
| `environment.systemPackages` | `[ pkgs.docker-compose pkgs.python3 pkgs.git pkgs.rsync ]` | `[ pkgs.htop pkgs.tmux pkgs.curl pkgs.rsync pkgs.git ]` (`identity.nix`) | **Not an error.** `environment.systemPackages` is `listOf package`; NixOS concatenates list-typed options from every module rather than requiring equality. Composing both is safe — the only cost is `git` and `rsync` appearing twice in the resulting list (cosmetically redundant, functionally harmless: Nix store paths dedupe at the derivation level regardless of list order/duplicates). Flagging it here because the task asked for every option both sides set, not just the ones that error.

No other `config`-level option path in `ac-host.nix` (firewall ports, `systemd.tmpfiles.rules`, its own `systemd.services.*`/`systemd.timers.*` units) overlaps anything in `modules/platform/*.nix`.

## modules/monitoring.nix

No collisions found. It touches `users.groups.monitoring`, `users.users.unifi-poller`/`grafana` (distinct from `identity.nix`'s `nixosuser`/`ac`/`root`), `networking.firewall.allowedTCPPorts = [ 3000 ]` (not set by any platform module — `network.nix` deliberately sets no firewall config, per its own header comment), and a large block of `services.prometheus.*`, `services.cadvisor`, `services.unpoller`, `services.grafana`, and its own `systemd.services.*` — none of which any platform module touches.

Worth flagging even though it isn't a `modules/platform/*.nix` collision: `monitoring.nix` hardcodes `192.168.1.50` three times (`services.grafana.settings.server.http_addr/domain/root_url`) as a second literal copy of the same LAN address that `arcade-hub.nix`'s `lanAddress` option and (once set) `homelab.host.networks.lan.address` also carry. It's exactly the kind of duplicate-literal drift `host-options.nix`'s and `network.nix`'s comments warn about for `arcade-hub`/`agent-hub` — `monitoring.nix` just hasn't been pulled into that pattern yet.

## modules/arcade-hub.nix (canonical, now in git)

No collisions found. `users.groups.arcade` / `users.users.arcade` are distinct from `identity.nix`'s accounts; `networking.firewall.interfaces.${cfg.gameInterface}.*` is a path no platform module writes to (`network.nix` explicitly declines to configure `networking.interfaces`/firewall); `services.samba`, `services.rsyncd`, its own `systemd.services.arcade-*`, and `assertions` are all untouched by platform modules.

## Config values only `hosts/ac-box/configuration.nix` supplies

- **`services.arcade-hub.lanAddress`** and **`services.arcade-hub.gameInterface`** — the canonical module declares both with no `default` (by design, per the module's own doc comment: "this is a host fact, not a tenant fact"). Nothing but `hosts/ac-box/configuration.nix` sets them today (this commit's `services.arcade-hub` block, with `lanAddress = "192.168.1.50"` / `gameInterface = "enp8s0"`). Evaluating `nixosConfigurations.ac-box` without that block, or with `services.arcade-hub.enable = true` set anywhere without also setting both, fails at the module's own `assertions` (`lanAddress != "0.0.0.0"`) or simply has no value to read. When this module is later consumed by the homelab platform repo, the analogous wiring is `services.arcade-hub.lanAddress = config.homelab.host.networks.lan.address;` / `.gameInterface = config.homelab.host.networks.lan.interface;` (the module's own comments say this explicitly) — `hosts/ac-box/configuration.nix`'s literal strings are the pre-platform stand-in for that.
- Everything else in `ac-host.nix` (`repoDir`, `stateDir`, `authOpen`, `requiredRole`, port ranges) and all of `ac-host-dev` have defaults, so `hosts/ac-box/configuration.nix` setting them explicitly is redundant-but-safe, not load-bearing. `monitoring.nix` has no `options` block at all — everything it sets is a literal, not read from `config` supplied elsewhere.

## Verification method

Confirmed with a standalone `lib.evalModules` test (not part of this repo) that two modules defining the same `bool` option to equal literal values merge without error, and to unequal values throw `"The option '<name>' has conflicting definition values"` — this is what backs the "risk, not yet a guaranteed failure" framing above for the two `virtualisation.docker.*` lines. `nix flake check` and `nix eval` results for this repo's own flake are in the accompanying task report, not repeated here.
