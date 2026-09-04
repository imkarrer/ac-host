{
  config,
  lib,
  pkgs,
  ...
}:

let
  secretsDir = "/var/lib/monitoring/secrets";
  grafanaAdminFile = "${secretsDir}/grafana-admin";
  grafanaSecretFile = "${secretsDir}/grafana-secret-key";
  unpollerPassFile = "${secretsDir}/unpoller.pass";
  discordWebhookFile = "${secretsDir}/discord-webhook";
  dashboardsDir = ./grafana-dashboards;
in
{
  users.groups.monitoring = { };

  systemd.tmpfiles.rules = [
    "d /var/lib/monitoring 0755 root root -"
    "d ${secretsDir} 0750 root monitoring -"
  ];

  system.activationScripts.monitoring-secrets = ''
    mkdir -p ${secretsDir}
    chmod 0750 ${secretsDir}
    chown root:monitoring ${secretsDir} || true
    if [ ! -s ${grafanaAdminFile} ]; then
      tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24 > ${grafanaAdminFile}
      echo "created Grafana admin password in ${grafanaAdminFile}"
    fi
    if [ ! -s ${grafanaSecretFile} ]; then
      tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 > ${grafanaSecretFile}
    fi
    chmod 0640 ${grafanaAdminFile} ${grafanaSecretFile} ${unpollerPassFile} ${discordWebhookFile} 2>/dev/null || true
    chown root:monitoring ${grafanaAdminFile} ${grafanaSecretFile} ${unpollerPassFile} ${discordWebhookFile} 2>/dev/null || true
  '';

  users.users.unifi-poller.extraGroups = [ "monitoring" ];
  users.users.grafana.extraGroups = [ "monitoring" ];

  networking.firewall.allowedTCPPorts = [ 3000 ];

  services.prometheus.exporters.node = {
    enable = true;
    listenAddress = "127.0.0.1";
    port = 9100;
    enabledCollectors = [
      "systemd"
      "filesystem"
    ];
  };

  services.cadvisor = {
    enable = true;
    listenAddress = "127.0.0.1";
    port = 9102;
    extraOptions = [
      "--docker_only=true"
      "--docker=unix:///run/docker.sock"
      "--containerd=/run/docker/containerd/containerd.sock"
      "--containerd-namespace=moby"
    ];
  };

  systemd.services.cadvisor.serviceConfig.SupplementaryGroups = [ "docker" ];

  services.unpoller = {
    enable = true;
    influxdb.disable = true;
    prometheus.http_listen = "127.0.0.1:9130";
    unifi = {
      controllers = [
        {
          url = "https://192.168.1.1";
          user = "unpoller";
          pass = unpollerPassFile;
          verify_ssl = false;
          sites = "default";
          save_dpi = false;
          save_ids = false;
          save_events = false;
          save_alarms = false;
          save_anomalies = false;
        }
      ];
    };
  };

  systemd.services.unifi-poller.unitConfig.ConditionPathExists = unpollerPassFile;

  systemd.services.docker-name-exporter = {
    description = "Map cAdvisor container ids to Docker names";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" "docker.service" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      ExecStart = "${pkgs.python3}/bin/python3 ${../scripts/docker_name_exporter.py}";
      Restart = "always";
      RestartSec = "10s";
      SupplementaryGroups = [ "docker" ];
      Environment = [
        "DOCKER_SOCK=/run/docker.sock"
        "DOCKER_API_VERSION=1.44"
        "DOCKER_NAME_BIND=127.0.0.1:9132"
      ];
    };
  };

  systemd.services.udr-fw-exporter = {
    description = "Dream Router firewall hit exporter";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.ConditionPathExists = unpollerPassFile;
    serviceConfig = {
      ExecStart = "${pkgs.python3}/bin/python3 ${../scripts/udr_fw_exporter.py}";
      Restart = "always";
      RestartSec = "10s";
      User = "unifi-poller";
      Group = "monitoring";
      Environment = [
        "UNIFI_HOST=https://192.168.1.1"
        "UNIFI_USER=unpoller"
        "UNIFI_PASS_FILE=${unpollerPassFile}"
        "UDR_FW_BIND=127.0.0.1:9131"
      ];
    };
  };

  services.prometheus = {
    enable = true;
    listenAddress = "127.0.0.1";
    port = 9090;
    retentionTime = "30d";
    alertmanagers = [
      {
        static_configs = [
          { targets = [ "127.0.0.1:9093" ]; }
        ];
      }
    ];
    scrapeConfigs = [
      {
        job_name = "node";
        static_configs = [ { targets = [ "127.0.0.1:9100" ]; } ];
      }
      {
        job_name = "cadvisor";
        static_configs = [ { targets = [ "127.0.0.1:9102" ]; } ];
      }
      {
        job_name = "unpoller";
        scrape_interval = "30s";
        static_configs = [ { targets = [ "127.0.0.1:9130" ]; } ];
      }
      {
        job_name = "udr-fw";
        scrape_interval = "30s";
        static_configs = [ { targets = [ "127.0.0.1:9131" ]; } ];
      }
      {
        job_name = "docker-names";
        scrape_interval = "15s";
        static_configs = [ { targets = [ "127.0.0.1:9132" ]; } ];
      }
    ];
    rules = [
      ''
        groups:
          - name: ac-box
            rules:
              - alert: AcBoxDiskHigh
                expr: 100 * (1 - node_filesystem_avail_bytes{mountpoint="/",fstype!="tmpfs"} / node_filesystem_size_bytes{mountpoint="/",fstype!="tmpfs"}) > 80
                for: 10m
                labels:
                  severity: warning
                annotations:
                  summary: "ac-box root disk is {{ $value | printf \"%.0f\" }}% full"

              - alert: AcBoxLoadHigh
                expr: node_load5 > 28
                for: 10m
                labels:
                  severity: warning
                annotations:
                  summary: "ac-box 5m load is {{ $value | printf \"%.1f\" }} (56 threads)"

              - alert: AcBoxMemLow
                expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.10
                for: 10m
                labels:
                  severity: warning
                annotations:
                  summary: "ac-box has under 10% RAM available"

              - alert: AcBoxExporterDown
                expr: up{job=~"node|cadvisor"} == 0
                for: 5m
                labels:
                  severity: warning
                annotations:
                  summary: "Prometheus scrape {{ $labels.job }} is down"

              - alert: UnpollerDown
                expr: up{job="unpoller"} == 0
                for: 10m
                labels:
                  severity: warning
                annotations:
                  summary: "unpoller is down or cannot reach the Dream Router API"

              - alert: UnifiGatewayCpuHigh
                expr: 100 * max(unpoller_device_cpu_utilization_ratio{type="udm"}) > 80
                for: 5m
                labels:
                  severity: warning
                annotations:
                  summary: "Dream Router CPU is {{ $value | printf \"%.0f\" }}%"

              - alert: UnifiGatewayMemHigh
                expr: 100 * max(unpoller_device_memory_utilization_ratio{type="udm"}) > 85
                for: 5m
                labels:
                  severity: warning
                annotations:
                  summary: "Dream Router RAM is {{ $value | printf \"%.0f\" }}%"

              - alert: PracticeLobbiesFailed
                expr: node_systemd_unit_state{name="ac-host-static.service",state="failed"} == 1
                for: 2m
                labels:
                  severity: critical
                annotations:
                  summary: "ac-host-static.service is failed — practice lobbies may be down"
      ''
    ];
  };

  services.prometheus.alertmanager = {
    enable = true;
    listenAddress = "127.0.0.1";
    port = 9093;
    configuration = {
      route = {
        receiver = "discord";
        group_by = [ "alertname" ];
        group_wait = "30s";
        group_interval = "5m";
        repeat_interval = "4h";
      };
      receivers = [
        {
          name = "discord";
          discord_configs = [
            {
              webhook_url_file = discordWebhookFile;
              send_resolved = true;
            }
          ];
        }
      ];
    };
  };

  systemd.services.alertmanager.serviceConfig.SupplementaryGroups = [ "monitoring" ];
  systemd.services.alertmanager.unitConfig.ConditionPathExists = discordWebhookFile;

  systemd.services.grafana.wants = [ "network-online.target" ];
  systemd.services.grafana.after = [ "network-online.target" ];
  systemd.services.grafana.serviceConfig.SupplementaryGroups = [ "monitoring" ];

  services.grafana = {
    enable = true;
    settings = {
      server = {
        http_addr = "192.168.1.50";
        http_port = 3000;
        domain = "192.168.1.50";
        root_url = "http://192.168.1.50:3000/";
        enable_gzip = true;
      };
      security = {
        admin_user = "admin";
        admin_password = "$__file{${grafanaAdminFile}}";
        secret_key = "$__file{${grafanaSecretFile}}";
        disable_initial_admin_creation = false;
      };
      "auth.anonymous" = {
        enabled = true;
        org_name = "Main Org.";
        org_role = "Viewer";
        hide_version = true;
      };
      analytics = {
        reporting_enabled = false;
        check_for_updates = false;
      };
      users.allow_sign_up = false;
    };
    provision = {
      datasources.settings.datasources = [
        {
          name = "Prometheus";
          type = "prometheus";
          uid = "prometheus";
          access = "proxy";
          url = "http://127.0.0.1:9090";
          isDefault = true;
          editable = false;
        }
      ];
      dashboards.settings.providers = [
        {
          name = "ac-host";
          type = "file";
          allowUiUpdates = true;
          options.path = "${dashboardsDir}";
        }
      ];
    };
  };
}
