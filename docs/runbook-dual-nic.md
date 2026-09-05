# Runbook: dual-NIC split — operator steps

Execution order for [`plan-dual-nic.md`](plan-dual-nic.md). That doc is the design and the reasoning; this one is the do-list.

## Access modes

| Tag | Means |
| --- | --- |
| **SSH** | Remote. Any working SSH path. |
| **HANDS** | Physical access to the box, but no login — plugging a cable in. |
| **CONSOLE** | Keyboard and monitor attached, logged in at the box, or reading the boot menu. |
| **WS** | On your workstation (PowerShell / UniFi UI). |

"CONSOLE-attended" means the commands run over SSH, but you must be sitting at the box with keyboard and monitor already attached, because the recovery path is the boot menu and nothing else can reach it.

## At a glance

| Step | What | Mode | Can lock you out? |
| --- | --- | --- | --- |
| 0 | Preflight inventory | SSH | no |
| 1 | Physical preconditions | HANDS + WS | no |
| 2 | Widen the boot-menu timeout | SSH | no |
| 3 | Prove console access | CONSOLE | no |
| 4 | Run the management cable | HANDS | no |
| 5 | Workstation static IP | WS | no |
| 6 | Management NIC up, still NetworkManager | SSH | no |
| 7 | systemd-networkd migration | CONSOLE-attended | **yes** |
| 8 | Scope game ports to the game NIC | SSH | no |
| 9 | `.env` split | SSH | no (breaks *players*, not you) |
| 10 | SSH + Grafana to management only | CONSOLE-attended | **yes** |
| 11 | Disable password auth | SSH | **yes** (if keys aren't working) |
| 12 | Restore boot timeout, update docs | SSH + WS | no |

Two steps genuinely need you at the box: **7** and **10**. Everything else is remote, plus one cable run and one proof-of-console. Step 11 can lock you out for a different reason and has its own gate.

A note on tooling: `ethtool`, `nc`, and `nmap` are **not** in this box's `environment.systemPackages`. The commands below use `/sys/class/net` and `curl` where possible, and `nix-shell -p` where not.

---

## Step 0 — Preflight inventory (SSH)

Identify which NIC is which *without touching the box*. The cabled one has carrier; the free one does not:

```bash
for n in /sys/class/net/en*; do
  i=$(basename "$n")
  echo "$i mac=$(cat $n/address) carrier=$(cat $n/carrier 2>/dev/null) speed=$(cat $n/speed 2>/dev/null)"
done
```

`carrier=1` is your `gameIface`. The other is `mgmtIface`. Write both names and MACs down — every later step keys off them, and getting them backwards means opening game ports on the management side.

If only **one** interface appears, the second NIC has no driver bound and none of this works yet:

```bash
lspci -nnk | grep -A3 -i ethernet
```

Look for a `Kernel driver in use:` line under both controllers. A missing one means you need the driver in `boot.kernelModules` or a firmware package before continuing.

Then capture the rest of the current state:

```bash
ip -br addr; ip route; cat /etc/resolv.conf
nmcli dev status; nmcli -f ipv4.method,ipv4.addresses con show
nixos-rebuild list-generations | head
git -C /var/lib/ac-host/src rev-parse HEAD
cp /var/lib/ac-host/.env ~/env.bak.$(date +%F)
```

The `ipv4.method` output tells you whether `192.168.1.50` is DHCP (a UDR reservation) or already static — plan §2 pins it statically either way, but you want to know which you're changing. Cross-check the reservation list in the UniFi UI **(WS)**, and leave any reservation in place so nothing else in the pool can claim the address.

## Step 1 — Physical preconditions (HANDS + WS)

Three yes/no questions. Any "no" changes the plan rather than the runbook:

1. **Is the workstation within Ethernet reach of the box?** If they are not in the same room, the direct-cable design does not apply — use the VLAN variant from the plan's rejected-alternatives section.
2. **Is the workstation's second NIC free?** `Get-NetAdapter` **(WS)**.
3. **Do you have a keyboard and monitor you can attach to the box?** Steps 7 and 10 are not safe without one.

## Step 2 — Widen the boot-menu timeout (SSH)

Do this before you need the boot menu, not while panicking in front of it:

```nix
boot.loader.timeout = 30;
```

Run `nixos-rebuild switch` from the repo directory (`cd /var/lib/ac-host/src`). Harmless — writes only to `/boot`. `configurationLimit = 5` is already set, so you have five generations to fall back to.

The reason: monitors on HDMI/DisplayPort often do not sync until several seconds after POST, especially behind an NVIDIA card. The NixOS default of 5 seconds can elapse entirely before the display wakes, and you will watch the box boot straight into the generation you were trying to escape.

If 30 seconds still isn't enough, `boot.loader.timeout = null` makes systemd-boot wait indefinitely (`menu-force`). Use that only inside the attended window and revert it in Step 12 — with `menu-force`, an unattended reboot after a power blip parks the box at the menu forever instead of coming back up.

Step 3 has you pressing keys at that menu, so know this in advance: **a stray `t` or `T` in systemd-boot writes a UEFI variable that overrides `boot.loader.timeout` entirely**, and no amount of rebuilding will fix it. If the timeout stops obeying config, clear it with `bootctl set-timeout ""` (and `bootctl set-default ""` for a hijacked default entry).

## Step 3 — Prove console access (CONSOLE)

Attach keyboard and monitor. Reboot. Confirm **both** of these — a TTY login alone is not sufficient:

- You can **see the systemd-boot generation menu** and arrow through it. This is the only recovery path for Steps 7 and 10.
- You can log in at the TTY and get a shell.

Do not continue until the menu is reliably visible.

## Step 4 — Run the management cable (HANDS)

Workstation NIC 2 → box `mgmtIface`. Hot-plug; the box stays up and no login is needed. A plain Cat5e/6 patch cable is fine, modern NICs auto-negotiate MDI-X.

Confirm over **SSH** that you cabled the NIC you think you did:

```bash
cat /sys/class/net/${mgmtIface}/carrier    # expect 1
cat /sys/class/net/${mgmtIface}/speed
```

To confirm visually which physical port is which, blink its LED for 30 seconds:

```bash
nix-shell -p ethtool --run "ethtool --identify ${mgmtIface} 30"
```

## Step 5 — Workstation static IP (WS)

```powershell
Get-NetAdapter
New-NetIPAddress -InterfaceAlias "Ethernet 2" -IPAddress 192.168.50.10 -PrefixLength 24
Get-NetIPConfiguration -InterfaceAlias "Ethernet 2"
```

**No gateway and no DNS on this adapter.** A gateway here has Windows trying to route internet traffic down a dead-end cable. Windows will label it "Unidentified network" and apply the Public firewall profile — fine, outbound SSH is unaffected.

Pinging the box still fails at this point. The box side is unconfigured until the next step; expected, not something to debug.

## Step 6 — Management NIC up, still on NetworkManager (SSH)

Apply the interim config: `networkmanager.unmanaged`, a static address via `networking.interfaces`, and a management-scoped firewall rule.

```nix
networking.networkmanager.unmanaged = [ "interface-name:${mgmtIface}" ];
networking.interfaces.${mgmtIface}.ipv4.addresses = [
  { address = mgmtIp; prefixLength = 24; }
];
networking.firewall.interfaces.${mgmtIface}.allowedTCPPorts = [ 22 ];
```

Leave the global firewall and SSH settings alone — the new interface rule is intentionally a no-op while the global rules are open. Safe over SSH: it touches only the NIC that had no configuration until Step 4, and the game NIC stays under NetworkManager exactly as it is. The scripted address job is deliberately kept out of `network.target`, so a missing interface cannot hang boot.

Verify from the existing SSH session:

```bash
ip -br addr            # both addresses present
ip route               # exactly ONE default, via 192.168.1.1 on gameIface
ip route get 8.8.8.8   # picks gameIface
```

Then from the workstation **(WS)**: `ping 192.168.50.50`, then `ssh "$AC_BOX_USER@192.168.50.50"`.

> **Gate — do not continue** until SSH over the direct cable works *and* the old path over `192.168.1.50` still works. Steps 7 and 10 assume two independent SSH paths plus console.

## Step 7 — systemd-networkd migration (CONSOLE-attended)

Keyboard and monitor attached **before** you start. This is the step most likely to leave the box off the network entirely, because it replaces the whole network stack at once.

Apply plan §1 and §2. **Delete the Step 6 block in the same commit** — do not layer networkd on top of it. With `useNetworkd = true`, `networking.interfaces` generates its own `.network` unit, so leaving those lines gives you two units matching one interface, resolved by filename order.

```bash
cd /var/lib/ac-host/src
nixos-rebuild boot --flake .#ac-box    # activates nothing; safe to run remotely
reboot
```

`boot` rather than `switch` is deliberate: swapping network stacks on a live system is messy, and the reboot proves the config survives one — which `switch` never tells you.

**(CONSOLE)** Watch it come back. If it does not, arrow to the previous generation in the boot menu and you are back to Step 6's state.

Then verify over **SSH**:

```bash
systemctl status systemd-networkd
networkctl status                  # both links should read "configured"
ip -br addr; ip route              # both addresses, ONE default
resolvectl status                  # DNS = 192.168.1.1
curl -sI https://cache.nixos.org   # proves DNS *and* routing
systemd-analyze blame | grep -i wait-online
docker ps                          # all lobbies back up
systemctl status ac-host-static
```

`curl` is the DNS check that matters. A box that routes fine but resolves nothing will ping `192.168.1.1` happily while nix builds and the Alertmanager Discord webhook fail.

**Then the carrier test, which is the whole reason §2 sets `ConfigureWithoutCarrier`.** **(HANDS)** Unplug the management cable at the box, reboot, and **SSH** in over the game NIC — still globally open at this point:

```bash
ip -br addr | grep 192.168.50.50           # address must STILL be present
networkctl status ${mgmtIface}             # "configured", not "configuring"
systemd-analyze blame | grep -i wait-online   # no ~2 minute entry
systemctl is-active sshd grafana              # both must be active
```

If the address is missing with the cable out, `ConfigureWithoutCarrier` or `LinkLocalAddressing` is wrong — **fix it before Step 10**, because Step 10 points `sshd` at that address and an unbindable `ListenAddress` kills sshd outright. Unplugging the cable is better than powering the workstation off, since you keep the workstation available to SSH from. Plug it back in when done.

## Step 8 — Scope game ports to the game NIC (SSH)

Apply plan §3. Safe remotely: SSH is still globally open, and this only narrows the game ports.

Verify from three directions. From the workstation over the management link **(WS)** — this must now **fail**:

```powershell
Test-NetConnection -ComputerName 192.168.50.50 -Port 9600
```

(Expect `TcpTestSucceeded : False` after a pause; `Test-NetConnection` is slow to give up.)

On the box:

```bash
ss -lntup | grep -E ':(96|80|81)[0-9][0-9]'   # 0.0.0.0 bindings are CORRECT here
systemctl status ac-host-static
docker ps                                      # check uptimes
```

Host-networked containers always bind everywhere; the firewall is the boundary. The failed `Test-NetConnection` from the management side is the actual proof the split works. Also confirm the rebuild did not restart `docker.service`, which would take every host-mode container with it.

From outside, confirm a real client still sees all three practice lobbies in the CM list and can join one.

## Step 9 — `.env` split (SSH)

Edit `/var/lib/ac-host/.env`. **Set `UNIFI_FWD_IP` first, then `AC_BOX_HOST`** — the order is the whole point, see plan §6.

```bash
python3 scripts/unifi_pf.py list    # every rule must still target 192.168.1.50
```

This cannot lock *you* out, and it cannot break player join links (those come from `AC_PUBLIC_IP`). Getting it backwards takes all three lobbies off the WAN while every log looks healthy. Do it while both SSH paths still work.

## Step 10 — SSH and Grafana to management only (CONSOLE-attended)

Keyboard and monitor attached. Requires Step 7's carrier test to have passed. Apply plan §4 and §5, then `nixos-rebuild switch`.

Verify with a **brand new SSH session** to `192.168.50.50`. Do not trust the session you already have — it survives an sshd restart and will tell you everything is fine while nothing can connect.

```bash
systemctl is-active sshd grafana
ss -lntp | grep -E ':(22|3000)'                     # bound to 192.168.50.50, not 0.0.0.0
curl -sI http://192.168.50.50:3000                  # Grafana here
curl -sI --max-time 3 http://192.168.1.50:3000      # and not here
```

From the workstation **(WS)**, `Test-NetConnection -ComputerName 192.168.1.50 -Port 22` must fail.

Recovery, in order: **(CONSOLE)** `nixos-rebuild switch --rollback`, or the previous generation from the boot menu.

To do this remotely instead, arm a deadman first and cancel it once a fresh session connects:

```bash
systemd-run --on-active=10m nixos-rebuild switch --rollback
systemctl list-timers 'run-*'      # find the transient unit
systemctl stop run-rXXXXX.timer    # cancel once you're satisfied
```

`--rollback` reactivates the previous generation without building, and one generation back is exactly this step undone — the payoff for one commit per phase. Note it only ever goes back **one** generation; anything older needs the boot menu.

## Step 11 — Disable password auth (SSH over management)

`PasswordAuthentication = false` and `KbdInteractiveAuthentication = false`.

> **Gate:** prove key-only auth works *before* applying. `ssh-keys.nix` in the repo is an empty list and real keys live in the gitignored `ssh-keys.local.nix`, so do not assume yours are installed:

```bash
ssh -o PreferredAuthentications=publickey -o PasswordAuthentication=no "$AC_BOX_USER@192.168.50.50" true
```

That must exit 0 for every account you rely on. If it prompts or fails, fix `ssh-keys.local.nix` and rebuild before touching this setting.

## Step 12 — Restore boot timeout, update docs (SSH + WS)

Put `boot.loader.timeout` back to a finite value (5 is the NixOS default) so an unattended reboot comes back up on its own. If you used `null` in Step 2, this matters — leaving it parks the box at the menu after any power blip.

Then update the places encoding the old single-address assumption: `README.md` "NixOS box" section, `compose/env.example` comments for `AC_BOX_HOST` and `UNIFI_FWD_IP`, and the `--host` default in `scripts/bootstrap_ssh.py`. Drop the now-dead `"networkmanager"` entry from `users.users.nixosuser.extraGroups` (harmless either way — nonexistent `extraGroups` entries are silently ignored, so this is tidying, not a fix). Optionally move deploys to `nixos-rebuild --target-host` over the management address.

---

## Recovery reference

**Some SSH path works.** Use it. `nixos-rebuild switch --rollback` goes back one generation, or revert the commit and rebuild.

**Box is up but unreachable on both paths.** CONSOLE, log in at the TTY, then `nixos-rebuild switch --rollback`. For diagnosis first: `networkctl status`, `ip -br addr`, `journalctl -b -u systemd-networkd`, and `systemctl status sshd` — if sshd is dead rather than unreachable, you are looking at the `ListenAddress`/carrier problem from Step 7.

**Box does not finish booting.** CONSOLE, boot menu, arrow to the previous generation. This is why Steps 2 and 3 exist.

**Boot menu ignores the configured timeout.** A stray `t` keypress set a UEFI override: `bootctl set-timeout ""`.

**Need NetworkManager back in a hurry, from the console.** Boot the pre-Step-7 generation — more than one generation back, so this is the boot menu, not `--rollback`. It stays available as long as you have not burned through `configurationLimit = 5` rebuilds since.

**Lobbies down but you can still SSH.** Almost certainly Step 9's ordering. Check `python3 scripts/unifi_pf.py list` for forwards pointing at `192.168.50.50` instead of `192.168.1.50`.
