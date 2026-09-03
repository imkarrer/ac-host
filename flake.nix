{
  description = "NixOS host for Assetto Corsa practice lobbies and race containers";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      nixosModules.ac-host = import ./modules/ac-host.nix;
      nixosModules.default = self.nixosModules.ac-host;

      nixosConfigurations.ac-box = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          self.nixosModules.ac-host
          ./hosts/ac-box/configuration.nix
        ];
      };

      formatter.${system} = pkgs.nixfmt-rfc-style;
    };
}
