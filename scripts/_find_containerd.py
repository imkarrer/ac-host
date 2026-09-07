from pathlib import Path
from subprocess import check_output

print(check_output(["find", "/run", "/var/run", "-name", "*containerd*.sock", "-o", "-name", "docker.sock"], text=True))
print("--- cadvisor-start ---")
print(check_output(["systemctl", "cat", "cadvisor"], text=True))
start = Path("/etc/systemd/system/cadvisor.service").resolve()
print("resolved", start)
print(check_output(["cat", "/nix/store/b6ra1h93sp46dr4jm721m7n7yvqigy4v-unit-script-cadvisor-start/bin/cadvisor-start"], text=True))
