# CueMs System main engine
## Settings
File _settings.xml_ has the main config data.

Run
```
python3 test_engine.py
```
to check out.

## Development: editable install from source

When the engine is installed under `/usr/lib/cuems` (e.g. via the Debian package), you can make the installed code point at this source tree so edits here are used without reinstalling:

```bash
# From the cuems-engine repo root (or set CUEMS_ENGINE_SRC to the repo root)
./scripts/link-dev.sh
```

This replaces `/usr/lib/cuems/lib/python3.11/site-packages/cuemsengine` with a symlink to `src/cuemsengine`. Restart the controller-engine and node-engine services (or processes) to pick up changes. To restore the installed package, reinstall the cuems-engine deb.


## Release notes

### v0.1.0
Initial release.
