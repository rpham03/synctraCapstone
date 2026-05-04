#!/usr/bin/env bash
# One-time (per Flutter upgrade) fix for: Target native_assets required define SdkRoot...
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/tool/patch_flutter_resident_sdkroot.py" "$@"
