# Windows GPU Worker

A manually-controlled, elastic GPU-backed model worker for whichever
Windows machine has a spare GPU — the first instance of the opportunistic
compute pool `body-design.md` Section 4.3/6.1 always specified but never
had real hardware for. Not a Proxmox guest, not a service, not
auto-started: you run `start.ps1` when you want it online, and close the
window (or Ctrl+C) when you don't. Nothing else in the system treats this
machine as a dependency — see `elastic_workers.py`'s module docstring and
`tests/test_elastic_workers.py`'s real kill-mid-session test.

## One-time setup

Everything below lives in `%USERPROFILE%\athenaeum-gpu-worker\` by
default (override with `$env:ATHENAEUM_GPU_WORKER_DIR`), **outside** this
git repo — it's multi-GB binaries and model weights, not source.

1. **Download a llama.cpp CUDA build matching your driver's CUDA
   version** (check with `nvidia-smi`, top-right corner) from
   [github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases):
   `llama-bNNNNN-bin-win-cuda-<version>-x64.zip` plus the matching
   `cudart-llama-bin-win-cuda-<version>-x64.zip` (CUDA runtime DLLs —
   needed unless you already have the full CUDA toolkit installed).
   Extract both into the worker directory.
2. **Download a model GGUF** into the same directory. The default here is
   OLMo 3 7B Instruct, matching the Proxmox model-lab's own verified
   source: `bartowski/allenai_Olmo-3-7B-Instruct-GGUF` →
   `allenai_Olmo-3-7B-Instruct-Q4_K_M.gguf` (~4.2GB, fits an 8GB card with
   headroom for other GPU use). Save it as `olmo3-7b.gguf` in the worker
   directory, or set `$env:ATHENAEUM_GPU_MODEL` to a different filename.

## Running

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

Serves on `http://0.0.0.0:8090` by default (`$env:ATHENAEUM_GPU_PORT` to
change) — reachable from the rest of the LAN (Proxmox guests, the test
suite on LXC 104) the same way the model-lab guests are.

`--no-jinja` is always passed: `llama-server` parses a model's chat
template at startup even though this project only ever uses the raw
`/completion` endpoint, and OLMo 3's template uses a Jinja filter
llama.cpp's built-in parser doesn't support — the same crash-loop bug
found and fixed for the CPU model-lab guests (`docs/brain-session-log.md`,
2026-09-23).

## Registering this worker with the rest of the system

Add (or confirm) an entry in `elastic_workers.yaml` at the repo root:

```yaml
workers:
  - name: your-machine-name
    endpoint: http://<this-machine's-LAN-IP>:8090
    models: [olmo3-7b]
```

That's the entire "registration" step — a one-line config edit, not a
push/handshake protocol. `elastic_workers.py` health-checks every worker
fresh before every real call, so adding a line here doesn't claim the
worker is up; it just makes it *discoverable* when it is.

## If VRAM is tight

`--n-gpu-layers 999` tells llama.cpp to offload as many layers as fit,
not literally 999 — but if the model doesn't fit alongside whatever else
is using the GPU (browser, games, other apps), lower
`$env:ATHENAEUM_GPU_LAYERS` to a smaller number for partial offload
(slower, but still faster than CPU-only, and won't fail to start).
