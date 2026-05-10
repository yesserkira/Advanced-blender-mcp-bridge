# Headless Blender integration tests

These tests load the add-on's capability modules into a real Blender
process and call the dispatcher directly. They require Blender 4.2+ on
PATH (or supplied explicitly).

## Run locally

```powershell
# Windows
& "C:\Program Files\Blender Foundation\Blender 4.3\blender.exe" `
  --background --factory-startup `
  --python tests/integration/run_in_blender.py
```

```bash
# Linux / macOS
blender --background --factory-startup \
  --python tests/integration/run_in_blender.py
```

You should see ~17 tests pass.

## What's covered

| File                              | What it exercises                        |
|-----------------------------------|------------------------------------------|
| `test_round_trip_query.py`        | `ping`, `describe_api`                   |
| `test_create_objects_real.py`     | `create_objects` (real + dry-run)        |
| `test_snapshot_diff.py`           | `scene.snapshot` (hash stability + diff) |
| `test_geonodes_scatter.py`        | All 6 `geonodes.*` ops + presets         |
| `test_dry_run.py`                 | Dry-run safety on `create` / `delete`    |

## CI

The `blender-integration` job in `.github/workflows/ci.yml` runs this
suite against Blender 4.2.0 and 4.3.0 on Linux. The Blender tarball is
cached per version.
