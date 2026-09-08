{
  description = "Assetto Corsa practice lobbies and race containers, as a NixOS module";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      # This repo is a TENANT. It is no longer a host configuration.
      #
      # ac-box's system closure is built by github:imkarrer/homelab, which owns
      # the platform layer, the tenant contract and hosts/ac-box/. Three things
      # that used to live here have gone, and each was a duplicate of something
      # homelab now owns:
      #
      #   nixosConfigurations.ac-box  A rebuild from this flake produced a system
      #                               with no platform layer, no tenant contract
      #                               and the old GLOBAL firewall rules. It would
      #                               have reverted the whole refactor silently,
      #                               with no error -- and docs/runbook-dual-nic.md
      #                               still told an operator to run exactly that.
      #
      #   nixosModules.arcade-hub     A hand-copied, mojibake-corrupted snapshot of
      #                               home-arcade's module, which had already
      #                               drifted: it carried a broken Mindustry
      #                               ExecStart long after the fix existed
      #                               upstream. homelab consumes the canonical one
      #                               from github:imkarrer/home-arcade.
      #
      #   nixosModules.monitoring     Prometheus/Grafana/Alertmanager: a service
      #                               every tenant depends on, owned by the repo of
      #                               one tenant. Now homelab/modules/observability.
      #
      # Keeping any of them here would recreate the vendored-duplicate problem the
      # refactor existed to remove.
      nixosModules.ac-host = import ./modules/ac-host.nix;
      nixosModules.default = self.nixosModules.ac-host;

      formatter.${system} = pkgs.nixfmt-rfc-style;
    };
}
