# Experiment: package the bot and sidecars so a run-mode environment can run
# them, the way Flox intends run mode to be used (see experiments/run-mode).
{
  stdenv,
  lib,
  makeWrapper,
  python312,
  dejavu_fonts,
  git,
  rsync,
  docker-client,
}:
let
  # withPackages bundles the interpreter with each library's whole dependency
  # tree (discordpy -> aiohttp, ...), which a run-mode environment never links.
  py = python312.withPackages (ps: with ps; [ discordpy numpy scipy pillow ]);
in
stdenv.mkDerivation {
  pname = "ac-host-services";
  version = "0.0.1";
  src = lib.fileset.toSource {
    root = ../..;
    fileset = lib.fileset.unions [ ../../bot ../../sidecar ../../shared ../../scripts ];
  };
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  installPhase = ''
    runHook preInstall
    roots=$out/lib/ac-host
    mkdir -p $roots $out/bin
    cp -r bot sidecar shared scripts $roots/
    for svc in sidecar/auth sidecar/details sidecar/plugin bot/bot; do
      makeWrapper ${py}/bin/python $out/bin/ac-host-$(basename $svc) \
        --add-flags "-u $roots/$svc.py" \
        --set PYTHONPATH $roots/scripts:$roots/bot:$roots/sidecar:$roots/shared \
        --set AC_NUMBER_FONT ${dejavu_fonts}/share/fonts/truetype/DejaVuSans.ttf
    done
    # The bot manages the repo tree, so it still needs these at run time.
    wrapProgram $out/bin/ac-host-bot --prefix PATH : ${lib.makeBinPath [ git rsync docker-client ]}
    runHook postInstall
  '';
}
