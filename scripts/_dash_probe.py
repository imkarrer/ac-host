import json
from urllib.parse import quote
from urllib.request import urlopen

QUERIES = [
    ("cpu", '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))'),
    ("ram_used", "node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes"),
    ("disk", '100 * (1 - node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"})'),
    ("load1", "node_load1"),
    ("load5", "node_load5"),
    ("ctr_cpu", 'sum by (container) (rate(container_cpu_usage_seconds_total{id=~".*docker-.*"}[5m]) * on(id) group_left(container) docker_container_info)'),
    ("ctr_ram", 'sum by (container) (container_memory_working_set_bytes{id=~".*docker-.*"} * on(id) group_left(container) docker_container_info)'),
    ("unifi_cpu", '100 * max by (name) (unpoller_device_cpu_utilization_ratio{type="udm"})'),
    ("unifi_mem", '100 * max by (name) (unpoller_device_memory_utilization_ratio{type="udm"})'),
    ("up", "up"),
    ("cadvisor_names", "count by (name) (container_memory_working_set_bytes)"),
    ("cadvisor_id_sample", "count by (id, name, image) (container_memory_working_set_bytes)"),
]


def query(expr: str) -> dict:
    url = "http://127.0.0.1:9090/api/v1/query?query=" + quote(expr)
    with urlopen(url, timeout=15) as resp:
        return json.load(resp)


for title, expr in QUERIES:
    data = query(expr)
    rows = data.get("data", {}).get("result", [])
    print(f"=== {title} n={len(rows)} ===")
    for row in rows[:20]:
        metric = {k: v for k, v in row.get("metric", {}).items() if k != "__name__"}
        val = row.get("value", [None, None])[1]
        print(metric, val)
