# Stands in for "flox publish, then install from the catalog": the runtime
# environment installs the same Nix expression through this flake, so the
# experiment needs no push, no publish and no CI run on the race server.
{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  outputs =
    { nixpkgs, ... }:
    {
      packages = nixpkgs.lib.genAttrs [ "aarch64-linux" "x86_64-linux" "aarch64-darwin" ] (system: {
        default = nixpkgs.legacyPackages.${system}.callPackage ../../.flox/pkgs/ac-host-services.nix { };
      });
    };
}
