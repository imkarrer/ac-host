from pathlib import Path
from subprocess import check_output
from urllib.request import urlopen

print("=== cadvisor unit ===")
print(check_output(["systemctl", "cat", "cadvisor"], text=True)[:2500])
print("=== cadvisor status ===")
print(check_output(["systemctl", "is-active", "cadvisor"], text=True))
print("=== journal ===")
print(check_output(["journalctl", "-u", "cadvisor", "-n", "40", "--no-pager"], text=True))
print("=== docker sock ===")
print(check_output(["ls", "-l", "/var/run/docker.sock"], text=True))
print("=== metric names ===")
text = urlopen("http://127.0.0.1:9102/metrics", timeout=15).read().decode()
names = sorted({line.split("{", 1)[0] for line in text.splitlines() if line.startswith("container_")})
print("\n".join(names[:80]))
print("series_with_name", sum(1 for line in text.splitlines() if 'name="' in line and not line.startswith("#")))
print("series_ac", sum(1 for line in text.splitlines() if "ac-" in line))
