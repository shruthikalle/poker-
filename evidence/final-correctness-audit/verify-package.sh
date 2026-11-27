#!/usr/bin/env bash
# From the repository root. Install Playwright Chromium before running this check.
set -eu
audit_root="$(mktemp -d "${TMPDIR:-/tmp}/poker-clean.XXXXXX")"
source_ref="${1:-HEAD}"
source_ref="$(git rev-parse "$source_ref")"
printf 'Temporary checkout %s\n' "$audit_root"
git clone --quiet --local --no-hardlinks . "$audit_root/checkout"
cd "$audit_root/checkout"
git switch --detach "$source_ref"
test -z "$(git status --porcelain)"
git rev-parse HEAD
printf '%s\n' '$ uv sync --locked --no-dev'
uv sync --locked --no-dev
uv run --offline --locked --no-dev python -c 'import sys; from importlib.util import find_spec; import poker.server; assert find_spec("playwright") is None; assert find_spec("httpx2") is None; print("Runtime only, Python", sys.version.split()[0])'
printf '%s\n' '$ uv sync --locked --group browser'
UV_PROJECT_ENVIRONMENT="$audit_root/browser-venv" uv sync --locked --group browser
run_app() {
  if curl --noproxy '*' -fsS http://127.0.0.1:8000/health > /dev/null 2>&1; then
    printf 'Port 8000 is serving a process already.\n' >&2
    return 1
  fi
  "$@" > "$audit_root/uvicorn.log" 2>&1 &
  audit_pid=$!
  trap 'kill "$audit_pid" 2>/dev/null || true' EXIT
  for attempt in {1..60}; do
    kill -0 "$audit_pid" 2>/dev/null || { cat "$audit_root/uvicorn.log"; return 1; }
    if curl --noproxy '*' -fsS http://127.0.0.1:8000/health > /dev/null 2>&1; then break; fi
    sleep 0.1
  done
  curl --noproxy '*' -fsS http://127.0.0.1:8000/health
  printf '\n'
  "$audit_root/browser-venv/bin/python" "$audit_root/checkout/evidence/final-correctness-audit/browser_audit.py" --case installed
  kill "$audit_pid"
  wait "$audit_pid" || test "$?" = 143
  trap - EXIT
}
printf '%s\n' '$ uv run --locked --no-dev uvicorn poker.server:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096'
run_app uv run --offline --locked --no-dev uvicorn poker.server:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
printf '\n%s\n' '$ uv build --offline --wheel'
uv build --offline --wheel --out-dir "$audit_root/dist"
uv run --offline --locked --no-dev python - "$audit_root"/dist/*.whl <<'PY'
import sys
import zipfile
with zipfile.ZipFile(sys.argv[1]) as wheel:
    names = set(wheel.namelist())
    assert {"poker/engine.py", "poker/server.py", "server/coordinator.py"} <= names
    assets = {name for name in names if name.startswith("server/static/")}
    assert assets == {"server/static/index.html", "server/static/styles.css", *(
        f"server/static/js/{module}.mjs"
        for module in ("app", "network", "render", "session", "state")
    )}
    assert all(name.split("/")[0] in {"poker", "server"} or ".dist-info/" in name for name in names)
    print(f"Wheel manifest: {len(assets)} frontend assets, no evidence, tests, environment or repository metadata")
PY
printf '\n%s\n' '$ uv sync --offline --locked --no-dev --no-install-project' '$ uv pip install --offline --no-deps --python <wheel venv>/bin/python <wheel>'
UV_PROJECT_ENVIRONMENT="$audit_root/wheel-venv" uv sync --offline --locked --no-dev --no-install-project
uv pip install --offline --no-deps --python "$audit_root/wheel-venv/bin/python" "$audit_root"/dist/*.whl
mkdir "$audit_root/installed-cwd"
cd "$audit_root/installed-cwd"
env -u PYTHONPATH "$audit_root/wheel-venv/bin/python" -c 'from importlib.util import find_spec; import poker.server; assert "site-packages" in poker.server.__file__; assert find_spec("playwright") is None; print("Installed package imported from site-packages outside the checkout")'
printf '%s\n' '$ <wheel venv>/bin/python -m uvicorn poker.server:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096'
run_app env -u PYTHONPATH "$audit_root/wheel-venv/bin/python" -m uvicorn poker.server:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --ws websockets-sansio --ws-max-size 4096
cd "$audit_root/checkout"
test -z "$(git status --porcelain)"
printf '%s\n' 'Clean checkout remained clean after verification.'
