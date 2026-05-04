#!/usr/bin/env python3
"""
Patch Flutter SDK: add SdkRoot to ResidentRunner's Environment.defines.

Fixes: Target native_assets required define SdkRoot but it was not provided
during hot reload / DevFS asset rebuild (flutter/flutter#180603).

After `flutter upgrade`, run this again if the error returns (upgrade may overwrite
packages/flutter_tools/lib/src/resident_runner.dart).

Usage:
  python3 tool/patch_flutter_resident_sdkroot.py apply
  python3 tool/patch_flutter_resident_sdkroot.py restore
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

MARKER = "PATCH_SYNCTRA_RESIDENT_SDKROOT"

OLD_BLOCK = re.compile(
    r"  late final _environment = Environment\(\n"
    r"    artifacts: globals\.artifacts!,\n"
    r"    logger: globals\.logger,\n"
    r"    cacheDir: globals\.cache\.getRoot\(\),\n"
    r"    engineVersion: globals\.flutterVersion\.engineRevision,\n"
    r"    fileSystem: globals\.fs,\n"
    r"    flutterRootDir: globals\.fs\.directory\(Cache\.flutterRoot\),\n"
    r"    outputDir: globals\.fs\.directory\(getBuildDirectory\(\)\),\n"
    r"    processManager: globals\.processManager,\n"
    r"    platform: globals\.platform,\n"
    r"    analytics: globals\.analytics,\n"
    r"    projectDir: globals\.fs\.directory\(projectRootPath\),\n"
    r"    packageConfigPath: debuggingOptions\.buildInfo\.packageConfigPath,\n"
    r"    generateDartPluginRegistry: generateDartPluginRegistry,\n"
    r"    defines: <String, String>\{\n"
    r"      // Needed for Dart plugin registry generation\.\n"
    r"      kTargetFile: mainPath,\n"
    r"      kBuildMode: debuggingOptions\.buildInfo\.mode\.cliName,\n"
    r"    \},\n"
    r"  \);",
    re.MULTILINE,
)

NEW_BLOCK = f"""  late final _environment = () {{
    // {MARKER}
    // Hot reload's native_assets (Dart hooks) needs SdkRoot in Environment.defines;
    // upstream ResidentRunner only set TargetFile + BuildMode (see flutter/flutter#180603).
    String? sdkRoot = globals.platform.environment['SDKROOT']?.trim();
    if ((sdkRoot == null || sdkRoot.isEmpty) && globals.platform.isMacOS) {{
      for (final sdkName in <String>['iphonesimulator', 'iphoneos']) {{
        try {{
          final result = globals.processManager.runSync(
            <String>['xcrun', '--sdk', sdkName, '--show-sdk-path'],
          );
          if (result.exitCode == 0) {{
            final out = result.stdout.toString().trim();
            if (out.isNotEmpty) {{
              sdkRoot = out;
              break;
            }}
          }}
        }} catch (_) {{
          // Missing Xcode; try next sdk or leave sdkRoot unset.
        }}
      }}
    }}
    return Environment(
    artifacts: globals.artifacts!,
    logger: globals.logger,
    cacheDir: globals.cache.getRoot(),
    engineVersion: globals.flutterVersion.engineRevision,
    fileSystem: globals.fs,
    flutterRootDir: globals.fs.directory(Cache.flutterRoot),
    outputDir: globals.fs.directory(getBuildDirectory()),
    processManager: globals.processManager,
    platform: globals.platform,
    analytics: globals.analytics,
    projectDir: globals.fs.directory(projectRootPath),
    packageConfigPath: debuggingOptions.buildInfo.packageConfigPath,
    generateDartPluginRegistry: generateDartPluginRegistry,
    defines: <String, String>{{
      // Needed for Dart plugin registry generation.
      kTargetFile: mainPath,
      kBuildMode: debuggingOptions.buildInfo.mode.cliName,
      if (sdkRoot != null && sdkRoot.isNotEmpty) kSdkRoot: sdkRoot,
    }},
    );
  }}();"""


def flutter_root() -> Path:
    which = shutil.which("flutter")
    if not which:
        sys.exit("flutter not found on PATH")
    resolved = Path(which).resolve()
    # .../bin/flutter -> SDK root is two levels up
    return resolved.parent.parent


def resident_path(root: Path) -> Path:
    return root / "packages/flutter_tools/lib/src/resident_runner.dart"


def invalidate_tool_snapshot(root: Path) -> None:
    stamp = root / "bin/cache/flutter_tools.stamp"
    if stamp.exists():
        stamp.unlink()
        print(f"Removed {stamp} (flutter_tools will rebuild on next flutter invocation)")


def cmd_apply() -> None:
    root = flutter_root()
    path = resident_path(root)
    if not path.is_file():
        sys.exit(f"Missing {path} (unexpected Flutter SDK layout)")

    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print("Already patched.")
        invalidate_tool_snapshot(root)
        return

    m = OLD_BLOCK.search(text)
    if not m:
        sys.exit(
            "Could not find the expected ResidentRunner Environment block.\n"
            "Your Flutter version may differ; compare with:\n"
            "  packages/flutter_tools/lib/src/resident_runner.dart\n"
            "around `late final _environment = Environment(`"
        )

    backup = path.with_suffix(path.suffix + ".bak-synctra")
    backup.write_text(text, encoding="utf-8")
    print(f"Wrote backup {backup}")

    path.write_text(OLD_BLOCK.sub(NEW_BLOCK, text, count=1), encoding="utf-8")
    print(f"Patched {path}")
    invalidate_tool_snapshot(root)
    print("Done. Run `flutter doctor` or `flutter run` once to rebuild the tool snapshot.")


def cmd_restore() -> None:
    root = flutter_root()
    path = resident_path(root)
    backup = path.with_suffix(path.suffix + ".bak-synctra")
    if not backup.is_file():
        sys.exit(f"No backup at {backup}")
    path.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
    backup.unlink()
    print(f"Restored {path} from backup")
    invalidate_tool_snapshot(root)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("apply", "restore"):
        print(__doc__.strip())
        sys.exit(2)
    if sys.argv[1] == "apply":
        cmd_apply()
    else:
        cmd_restore()


if __name__ == "__main__":
    main()
