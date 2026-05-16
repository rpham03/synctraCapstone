#!/usr/bin/env bash
# Run the app on iOS with Xcode env set so Flutter's native_assets step always sees SdkRoot
# (avoids "Target native_assets required define SdkRoot but it was not provided" on some hot reloads).
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
if [[ -z "${SDKROOT:-}" ]]; then
  export SDKROOT="$(xcrun --sdk iphonesimulator --show-sdk-path)"
fi
cd "$APP_DIR"
exec flutter run "$@"
