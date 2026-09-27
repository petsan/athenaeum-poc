#!/bin/sh
# Athenaeum's nightly evaluation on LXC 104 (batch 12, phase BA; owner decisions D16, D19).
#   1. the release evaluation (every suite) into evals/runs/<UTC timestamp>/
#   2. the fault matrix and the dashboard page, over every kept run
#   3. keep the newest 90 runs
#   4. publish the page and the newest run's report to LXC 250 /athenaeum/
# A failing verdict is a result, not an error: the run is kept and published.
# Only a broken harness (no results file) stops before publishing.
set -eu

ROOT=${ATHENAEUM_ROOT:-/root/athenaeum-poc}
PY=${ATHENAEUM_PYTHON:-/opt/athenaeum-venv/bin/python}
KEEP=${ATHENAEUM_KEEP_RUNS:-90}
PUBLISH_TO=${ATHENAEUM_PUBLISH_TO:-athenaeum-pub@192.168.0.104}
KEY=${ATHENAEUM_PUBLISH_KEY:-/root/.ssh/athenaeum_dashboard}

exec 9>/run/athenaeum-nightly.lock
flock -n 9 || { echo "another nightly run holds the lock; skipping"; exit 0; }

cd "$ROOT"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
run="evals/runs/$stamp"
mkdir -p "$run"
echo "== evaluation -> $run"
"$PY" scripts/run_evals.py --out "$run" > "$run/run.log" 2>&1 || true
tail -n 20 "$run/run.log"
[ -f "$run/eval_results.json" ] || { echo "no eval_results.json: the harness failed; see $run/run.log" >&2; exit 1; }

echo "== keeping the newest $KEEP runs"
ls -1d evals/runs/*/ 2>/dev/null | sort | head -n "-$KEEP" | while read -r old; do rm -rf -- "$old"; done

echo "== fault matrix and dashboard"
"$PY" scripts/build_dashboard.py --runs evals/runs --out evals/out/dashboard
mkdir -p evals/out/dashboard/latest
cp "$run/eval_report.html" "$run/EVAL_CARD.md" "$run/eval_results.json" evals/out/dashboard/latest/

if [ -f "$KEY" ]; then
    echo "== publishing to $PUBLISH_TO"
    tar -C evals/out/dashboard -cf - . | ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=20 "$PUBLISH_TO" publish
else
    echo "== not published: no key at $KEY (see infra/nightly/README.md)"
fi
