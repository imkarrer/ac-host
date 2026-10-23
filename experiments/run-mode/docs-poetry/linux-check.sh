set -u
cd /work && git init -q && git add -A && git -c user.email=x@x -c user.name=x commit -qm x
flox build myproject 2>&1 | tail -3
echo "== activated dev shell:"; flox activate -- ./result-myproject/bin/hello
echo "== bare, as in a run-mode image:"; env -i PATH=/usr/bin:/bin ./result-myproject/bin/hello 2>&1 | tail -3
echo "== in a run-mode environment that installs the package:"
mkdir -p /rt && cd /rt && flox init -q >/dev/null 2>&1
flox install "$(readlink -f /work/result-myproject)" >/dev/null 2>&1 || echo "store-path install failed"
flox activate --mode run -- hello 2>&1 | tail -3
