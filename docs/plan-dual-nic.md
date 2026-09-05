# Plan: dual-NIC split — game traffic vs. operational (SSH) network

## Why

`ac-box` has two physical NICs but only one is in use. Everything — player game traffic, SSH, Grafana, Prometheus, UniFi polling — shares `192.168.1.50`. Splitting them gives:

- **Blast radius**: SSH and Grafana stop living on the same address the WAN port-forwards point at.
- **Clean firewall story**: game ports open *only* on the interface facing players; management ports *only* on the private side. Today both are global.
- **Out-of-band access**: a direct workstation link keeps working when the Dream Router is rebooting, wedged, or mid-upgrade — exactly when you want SSH.

Read [Honest limits](#honest-limits) before assuming this fixes player latency. For ordered operator steps and which ones need a keyboard attached, see [`runbook-dual-nic.md`](runbook-dual-nic.md).

## Decisions taken

- **Management segment**: direct cable, workstation NIC 2 → box NIC 2. **No VLAN.** A VLAN only helps if the UDR needs to route/firewall the management path, and it does not — the management interface has no gateway by design.
- **Grafana**: management interface only.
- **Network stack**: migrate the box from NetworkManager to **systemd-networkd**, fully declarative.
- **Break-glass**: physical console. No Tailscale.

Consequence of the first two together: **Grafana and SSH become reachable only from that one workstation.** For dashboards from a phone or laptop, put an unmanaged switch on the management segment — same design, still no VLAN.

## Current state

| Thing | Today |
| --- | --- |
| Addressing | NetworkManager, single NIC, `192.168.1.50`, gateway `192.168.1.1` (UDR) |
| Game ports | `9600–9615` TCP+UDP, `8081–8096` TCP, `8181–8196` TCP — **global** in [`../modules/ac-host.nix`](../modules/ac-host.nix) |
| Grafana | TCP `3000` global; `http_addr`/`domain`/`root_url` hardcoded to `192.168.1.50` in [`../modules/monitoring.nix`](../modules/monitoring.nix) |
| SSH | `22` opened globally by `services.openssh` default `openFirewall`; password auth still on |
| Containers | every AC container is `network_mode: host` — they bind `0.0.0.0` on **both** NICs, and `acServer` has no bind-address option |
| Already loopback-only | auth sidecars `18080`/`18081`, node exporter `9100`, cAdvisor `9102`, unpoller `9130`, UDR/docker exporters `9131`/`9132`, Prometheus `9090`, Alertmanager `9093` |

The loopback-only services need no work. The whole job is the four rows above them.

### What actually reads `AC_BOX_HOST`

Only two consumers, confirmed in [`../scripts/settings.py`](../scripts/settings.py):

- `unifi_fwd_ip()` — `UNIFI_FWD_IP` **or** `AC_BOX_HOST` as fallback
- `bootstrap_ssh.py --host` default

Player-facing join links come from `join_url()`, which uses `public_ip()` (`AC_PUBLIC_IP`, the WAN address) and never `box_host()`. So the `.env` split in §6 cannot break CM join links or the player page — the only exposure is port forwards.

## Target design

**`game` NIC** — already cabled to the LAN switch
- VLAN 1 / `192.168.1.0/24`, **keeps `192.168.1.50`**, now statically assigned
- Holds the **only** default route (`192.168.1.1`) and carries all outbound traffic
- Inbound: game `9600+N` TCP+UDP, HTTP `8081+N`, details `8181+N` — nothing else
- Receives the UniFi WAN port-forwards, unchanged

**`mgmt` NIC** — direct cable to the workstation
- `192.168.50.0/24`, static `192.168.50.50/24` on the box, `192.168.50.10/24` on the workstation
- **No default gateway on either end**
- Inbound on the box: TCP `22` and `3000`

Keeping `192.168.1.50` on the game side is deliberate: port forwards and `AC_PUBLIC_IP` reference that path. The management side is new, so it absorbs the churn.

**Why no gateway on the management link.** A second default route would send some outbound traffic down a dead-end cable, where it is simply blackholed — Discord webhooks from Alertmanager, UniFi polling at `192.168.1.1`, nix substituters, and the AC lobby registration Kunos needs would fail intermittently depending on route metrics and source selection. Note this is *not* a public-IP problem: both NICs sit behind the same WAN address (`167.237.13.200`), so NAT would be identical either way. The failure mode is a blackhole, not a mismatch.

### Rejected alternatives

- **VLAN on the UniFi switch** — more moving parts, and it puts the UDR back in the management path. Only worth it if many devices need management access.
- **Both NICs on `192.168.1.0/24`** — ARP flux, unpredictable source selection, needs `arp_ignore=1`/`arp_announce=2` plus policy routing.
- **Bond/LAG** — aggregation, the opposite of the isolation wanted.
- **Bind services per-interface instead of firewalling** — impossible for `acServer`; no bind option, and it runs host-networked.

## Nix changes

### 1. Interface names

Use the existing predictable names (`enp…`) rather than renaming. Renaming means `.link` files and a link bounce for no real gain, since `enp*` names are stable unless hardware moves. Bind them once:

```nix
let
  gameIface = "enpXsY";   # fill in from runbook Step 0
  mgmtIface = "enpAsB";
  mgmtIp    = "192.168.50.50";
in
```

Add assertions so a wrong or vanished NIC fails the build instead of silently opening game ports on the management side:

```nix
assertions = [
  { assertion = builtins.pathExists "/sys/class/net/${gameIface}";
    message = "game interface ${gameIface} not present"; }
  { assertion = builtins.pathExists "/sys/class/net/${mgmtIface}";
    message = "mgmt interface ${mgmtIface} not present"; }
];
```

These only fire on the machine doing the build. They are a guard against typos and hardware changes, not a substitute for the runbook's Step 0 inventory.

### 2. systemd-networkd migration

```nix
networking.networkmanager.enable = false;
networking.useNetworkd = true;
networking.useDHCP = false;
services.resolved.enable = true;
networking.nameservers = [ "192.168.1.1" ];

systemd.network.networks."10-game" = {
  matchConfig.Name = gameIface;
  address = [ "192.168.1.50/24" ];
  routes = [ { Gateway = "192.168.1.1"; } ];
  networkConfig.IPv6AcceptRA = false;
  dns = [ "192.168.1.1" ];
  linkConfig.RequiredForOnline = "routable";
};

systemd.network.networks."20-mgmt" = {
  matchConfig.Name = mgmtIface;
  address = [ "${mgmtIp}/24" ];
  networkConfig = {
    ConfigureWithoutCarrier = true;
    LinkLocalAddressing = "no";
    IPv6AcceptRA = false;
    DHCP = "no";
  };
  linkConfig.RequiredForOnline = "no-carrier";
};
```

Five things that will bite during this migration.

**`ConfigureWithoutCarrier = true` is mandatory, and this is the subtle one.** It defaults to **false**, meaning systemd-networkd will not assign an address to a link with no carrier. The management link is a direct cable to a workstation that gets powered off, and when it is off there is no carrier. Without this setting the box boots with **no `192.168.50.50` at all** — which means `services.openssh.listenAddresses` pointing at it makes **sshd fail to start outright** (a `ListenAddress` that cannot be bound is fatal, not a warning), and Grafana fails to bind for the same reason. You would have a box whose only SSH path exists solely while your desktop happens to be on. Enabling it also implicitly enables `IgnoreCarrierLoss`, so the address survives unplugging the cable at runtime, which is what you want.

`LinkLocalAddressing = "no"` is part of the same fix. Duplicate Address Detection requires carrier, and it is on by default for all IPv6 addresses — including the automatic IPv6 link-local one. Leave it enabled and the interface can sit in `configuring` forever with no carrier, defeating `ConfigureWithoutCarrier`. Our IPv4 static needs no `DuplicateAddressDetection = "none"` because DAD only defaults on for IPv4 *link-local* (`169.254.0.0/16`) addresses, and `192.168.50.50` is not one. If you ever renumber this link into `169.254.x`, you will need that too.

**`RequiredForOnline = "no-carrier"`** keeps `systemd-networkd-wait-online` from blocking on the unplugged link, which would delay `network-online.target` and with it `grafana`, `docker-name-exporter`, and `udr-fw-exporter`. Boot would appear to hang for two minutes whenever the workstation is off. `"no-carrier"` is the value upstream recommends alongside `ConfigureWithoutCarrier`; plain `"no"` also stops the wait but is less precise about why.

**DNS breaks silently without `services.resolved`.** NetworkManager was writing `/etc/resolv.conf`; networkd does not. Enabling resolved symlinks `/etc/resolv.conf` to the stub resolver and feeds `networking.nameservers` into `DNS=`. The per-link `dns` on the game network is the scoped answer and `networking.nameservers` is the global fallback — belt and braces, because the symptom otherwise is a box that routes perfectly and resolves nothing, so nix builds and the Discord webhook fail while `ping 192.168.1.1` looks healthy.

**Delete the Phase-1 management config; do not layer on top of it.** `networking.useNetworkd = true` makes `networking.interfaces` generate its *own* `.network` unit, so leaving the earlier `networking.interfaces.${mgmtIface}` and `networkmanager.unmanaged` lines in place gives you two units matching one interface, resolved by filename order. It happens to work and it is a trap for the next reader. Remove them in the same commit.

On `routes`: the flattened `{ Gateway = …; }` form above is current, and nixpkgs still accepts the older `{ routeConfig = { Gateway = …; }; }` via a legacy-key shim, so both evaluate.

### 3. `modules/ac-host.nix` — scope the game ports

Add a `gameInterface` option, then move the three port lists off the global set:

```nix
networking.firewall.interfaces.${cfg.gameInterface} = {
  allowedTCPPorts = (portList cfg.gamePortStart cfg.gamePortCount)
    ++ (portList cfg.httpPortStart cfg.gamePortCount)
    ++ (portList cfg.detailsPortStart cfg.gamePortCount);
  allowedUDPPorts = portList cfg.gamePortStart cfg.gamePortCount;
};
```

This is a genuine narrowing. In the firewall module the global options are folded into an internal `allInterfaces` as a pseudo-interface literally named `default`, matched with no `-i`, and merged with whatever you put in `interfaces` — so moving ports from the global list to an interface key changes them from all-interfaces to one-interface, rather than adding a redundant rule.

`networking.firewall.checkReversePath` defaults to `"loose"` and needs no change: the management link is on-link with no routing, so nothing here is asymmetric.

### 4. `modules/monitoring.nix` — Grafana onto mgmt

Replace `networking.firewall.allowedTCPPorts = [ 3000 ]` with `networking.firewall.interfaces.${mgmtIface}.allowedTCPPorts = [ 3000 ]`, and swap the three hardcoded `192.168.1.50` occurrences (`http_addr`, `domain`, `root_url`) for `mgmtIp`. Leave `https://192.168.1.1` alone — that is the UniFi controller, reached over the default route.

Grafana already has `after = [ "network-online.target" ]`, but with `RequiredForOnline = "no-carrier"` that target no longer implies the management link is up. `ConfigureWithoutCarrier` from §2 is what makes the bind succeed anyway; without it this module is the second thing to crash-loop after sshd.

### 5. SSH onto mgmt

```nix
services.openssh.openFirewall = false;
services.openssh.listenAddresses = [
  { addr = mgmtIp; port = 22; }
  { addr = "127.0.0.1"; port = 22; }
];
networking.firewall.interfaces.${mgmtIface}.allowedTCPPorts = [ 22 3000 ];
```

`listenAddresses` is not additive — once set, sshd stops listening anywhere else, which is why `127.0.0.1` is explicit for anything that SSHes to itself. This option is also the reason §2's `ConfigureWithoutCarrier` matters: sshd treats an unbindable `ListenAddress` as fatal.

Resist `networking.firewall.trustedInterfaces = [ mgmtIface ]`. It works, but explicit ports are what make the intent auditable in six months.

### 6. `.env` on the box — the one that will bite you

`unifi_fwd_ip()` resolves as `UNIFI_FWD_IP` **or** `AC_BOX_HOST`. Today `AC_BOX_HOST=192.168.1.50` does double duty as both "where I SSH" and "where the WAN forwards land". After the split those diverge. In `/var/lib/ac-host/.env`, **set `UNIFI_FWD_IP` before you touch `AC_BOX_HOST`**:

```
UNIFI_FWD_IP=192.168.1.50    # game NIC — port-forward target
AC_BOX_HOST=192.168.50.50    # mgmt NIC — SSH/deploy target
```

Change `AC_BOX_HOST` first and the next `up-static` retargets every forward at the management IP. All three lobbies go dark from the WAN with nothing in the logs looking wrong. Player join links are unaffected either way — see [What actually reads `AC_BOX_HOST`](#what-actually-reads-ac_box_host).

### 7. Leftovers to clean up

`users.users.nixosuser.extraGroups` contains `"networkmanager"`. Disabling NetworkManager removes that group, but this is **not** a build failure: NixOS's undefined-group assertion covers a user's *primary* group only, and nonexistent entries in `extraGroups` are silently dropped. So it is dead config rather than a blocker — remove it for tidiness, and do not go hunting for an eval error that will not appear.

## Honest limits

**This will not reduce player latency or jitter.** Both NICs share one WAN uplink and one Dream Router. If players see lag, the bottleneck is upstream bandwidth or router queueing, and the fix is smart queues / per-port QoS on the UDR. The second NIC buys isolation and reliable access, not throughput.

Two more. AC lobby registration depends on the box's outbound traffic working, which is why the default route must stay on the game NIC and the management link must have no gateway. And if `192.168.1.50` is a MAC-keyed DHCP reservation, swapping which physical port is "game" silently costs you the address and every port forward with it — §2 pins it statically, but leave the reservation in place so nothing else in the pool can claim it.

## Out of scope

- Dream Router QoS / smart queues (separate effort, and the real latency lever)
- IPv6 on either interface — `IPv6AcceptRA = false` and `LinkLocalAddressing = "no"` above are deliberate
- Moving Prometheus/Alertmanager off loopback
- Multi-device management access (add an unmanaged switch to the segment if wanted)
- Any change to [`plan-unifi-portforwards.md`](plan-unifi-portforwards.md) — independent, but do §6 before flipping `UNIFI_PF=1`
