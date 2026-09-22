# Starts a local GPU-backed llama-server, foreground, manual, on-demand.
#
# Deliberately NOT a Windows service and NOT auto-started: this worker is
# meant to be brought online/offline entirely at the operator's will
# (body-design.md Section 4.3/6.1 -- opportunistic compute is "never a
# dependency"). Running this script IS "bringing it online"; closing the
# window (or Ctrl+C) IS "bringing it offline" -- no separate stop script,
# no hidden background process to forget about. The rest of the system
# (elastic_workers.py) already treats this worker's absence as routine,
# proven by a real test that kills it mid-session and confirms graceful
# CPU fallback with zero crash (see tests/test_elastic_workers.py).
#
# Prerequisites (one-time, see README.md for how these got there):
#   - llama-server.exe + its DLLs (llama.cpp CUDA build) in this same
#     directory as this script's $WorkerDir, OR set $env:ATHENAEUM_GPU_WORKER_DIR.
#   - The model GGUF downloaded into that same directory.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File start.ps1
#   (or just right-click > Run with PowerShell)

$ErrorActionPreference = "Stop"

$WorkerDir = if ($env:ATHENAEUM_GPU_WORKER_DIR) { $env:ATHENAEUM_GPU_WORKER_DIR } else { "$HOME\athenaeum-gpu-worker" }
$ModelFile = if ($env:ATHENAEUM_GPU_MODEL) { $env:ATHENAEUM_GPU_MODEL } else { "olmo3-7b.gguf" }
$Port = if ($env:ATHENAEUM_GPU_PORT) { $env:ATHENAEUM_GPU_PORT } else { "8090" }
$NGpuLayers = if ($env:ATHENAEUM_GPU_LAYERS) { $env:ATHENAEUM_GPU_LAYERS } else { "999" }  # 999 = offload everything that fits

$ServerExe = Join-Path $WorkerDir "llama-server.exe"
$ModelPath = Join-Path $WorkerDir $ModelFile

if (-not (Test-Path $ServerExe)) {
    throw "llama-server.exe not found at $ServerExe -- see README.md for setup."
}
if (-not (Test-Path $ModelPath)) {
    throw "Model not found at $ModelPath -- see README.md for the download step."
}

Write-Host "Starting GPU worker: $ModelFile on port $Port (Ctrl+C or close this window to take it offline)"
& $ServerExe --model $ModelPath --host 0.0.0.0 --port $Port -c 4096 --n-gpu-layers $NGpuLayers --no-jinja
