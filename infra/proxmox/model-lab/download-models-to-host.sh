#!/usr/bin/env bash
# Run this ON THE PROXMOX HOST, as root. Downloads every model in
# manifest.tsv into the host's model store (owner, 2026-09-27: all models
# live in /mnt/pve/glacier-01), one folder per Hugging Face repo:
#
#   /mnt/pve/glacier-01/models/<repo name>/<file>
#   e.g. .../models/Qwen2.5-1.5B-Instruct-GGUF/qwen2.5-1.5b-instruct-q4_k_m.gguf
#
# The model-lab guests mount that folder read-only at /opt/models (see
# create-model-vms.sh), so a rebuilt guest needs no download of its own,
# and losing a guest's disk no longer loses its model (known-bugs.md #37).
#
# Resumable and idempotent: a complete file (size matches Hugging Face's)
# is skipped; a partial one is continued. Uses curl only: no Python, no
# huggingface_hub on the host.
#
# Also takes a plain list of models to keep in the store without a guest
# of their own (stored-models.tsv: two columns, hf_repo and hf_file).
#
# Usage:
#   ./download-models-to-host.sh [manifest.tsv]
#   ./download-models-to-host.sh stored-models.tsv
#   MODEL_STORE=/some/other/dir ./download-models-to-host.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
MANIFEST="${1:-manifest.tsv}"
STORE="${MODEL_STORE:-/mnt/pve/glacier-01/models}"
[[ -d "$(dirname "$STORE")" ]] || { echo "$(dirname "$STORE") is missing -- is the storage mounted?" >&2; exit 1; }

failed=0
while IFS=$'\t' read -r -a cols; do
    [[ ${#cols[@]} -eq 0 || "${cols[0]}" =~ ^# ]] && continue
    if [[ ${#cols[@]} -eq 2 ]]; then          # stored-models.tsv: hf_repo hf_file
        hf_repo="${cols[0]}" hf_file="${cols[1]}" label="${cols[1]%.gguf}"
    else                                      # manifest.tsv: label ... hf_repo hf_file
        label="${cols[0]}" hf_repo="${cols[8]}" hf_file="${cols[9]}"
    fi
    dir="$STORE/${hf_repo##*/}"
    dest="$dir/$hf_file"
    url="https://huggingface.co/${hf_repo}/resolve/main/${hf_file}"
    # the size Hugging Face reports for the file, to tell complete from partial,
    # and its SHA-256 (the LFS etag), to tell intact from damaged
    headers=$(curl -sIL "$url" | tr -d '\r')
    want=$(awk 'tolower($1)=="x-linked-size:" {print $2}' <<<"$headers" | tail -1)
    want_sha=$(awk 'tolower($1)=="x-linked-etag:" {print $2}' <<<"$headers" | tail -1 | tr -d '"')
    have=$(stat -c %s "$dest" 2>/dev/null || echo 0)
    if [[ -n "$want" && "$have" == "$want" ]]; then
        echo "$label: present ($dest, $have bytes)"
        continue
    fi
    echo "$label: downloading $hf_repo/$hf_file (${want:-unknown} bytes) -> $dir"
    mkdir -p "$dir"
    if ! curl -L --fail --retry 5 -C - -s -o "$dest" "$url"; then
        echo "$label: FAILED" >&2
        failed=1
        continue
    fi
    have=$(stat -c %s "$dest")
    if [[ -n "$want" && "$have" != "$want" ]]; then
        echo "$label: size $have != expected $want" >&2
        failed=1
        continue
    fi
    # Size isn't integrity: two writers resuming the same file (it happened,
    # 2026-09-27) leave the right size and the wrong bytes. A damaged file is
    # deleted, so the next run downloads it afresh instead of "resuming" it.
    if [[ ${#want_sha} -eq 64 ]]; then
        have_sha=$(sha256sum "$dest" | cut -d' ' -f1)
        if [[ "$have_sha" != "$want_sha" ]]; then
            echo "$label: SHA-256 mismatch (got $have_sha, want $want_sha); deleted, re-run to fetch it again" >&2
            rm -f "$dest"
            failed=1
            continue
        fi
    fi
    echo "$label: done ($have bytes${want_sha:+, sha256 ok})"
    chmod -R a+rX "$dir"   # unprivileged guests read these as "other"; touch only what this script made
done < "$MANIFEST"

exit $failed
