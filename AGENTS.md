# Repository Guidelines

## Project Structure & Module Organization
Primary entry points live in `azw2zip.py` and `azw2zip_nodedrm.py`, which orchestrate conversion and DRM handling. Shared helpers sit in `azw2zip_config.py`, `safefilename.py`, and the package under `src/azw2zip/`. Vendored tooling stays in `DeDRM_Plugin/`, `KindleUnpack/`, and the `DumpAZW6_*.py` scripts—update them only when tracking upstream sources. Configuration examples reside in `azw2zip.sample.json`, and `build.cmd` drives Windows packaging via Nuitka.

## Build, Test, and Development Commands
- `python -m venv .venv && .venv/Scripts/activate` sets up a local Python 3.10 workspace.
- `python -m pip install -e .` installs runtime dependencies listed in `pyproject.toml` for iterative development.
- `python azw2zip.py -z "X:\My Kindle Content" "X:\Comic"` converts AZW/KFX content to image-only ZIP/EPUB output.
- `python azw2zip.py --help` reviews CLI switches before extending workflows.
- `build.cmd` runs the Rye/Nuitka bundle, emitting an executable under `build/out/`; activate the venv first so Nuitka resolves modules.

## Coding Style & Naming Conventions
Follow standard Python style: 4-space indentation, snake_case functions, and UPPER_CASE constants. Keep CLI option names aligned with the existing argparse flags in `azw2zip.py`. JSON configuration keys mirror the sample file’s snake_case pattern; include inline `"//"` comments when adding guidance. Avoid reformatting vendored modules—local fixes should be isolated and documented in commit messages.

## Testing Guidelines
There is no automated test harness. Validate changes by running representative conversions with and without DRM, using `azw2zip.sample.json` as a base and ensuring generated archives unzip cleanly. When altering rename logic, craft focused sample entries in the JSON and confirm the resulting directory and filename templates match expectations.

## Commit & Pull Request Guidelines
Keep commit subjects short and descriptive, mirroring the existing Git history (concise statements, often in Japanese, no trailing period). Group unrelated work into separate commits and describe user impact in the body when needed. Pull requests should summarize the problem, outline the solution, note any manual verification steps, and link relevant issues or upstream updates. Include before/after samples for filename or metadata changes so reviewers can validate outcomes quickly.

## Security & Configuration Tips
Treat `azw2zip.sample.json` as reference only—store real credentials or key paths in a private copy. Verify file permissions on generated `k4i` key files before sharing builds. When distributing binaries from `build/out/`, document the source commit and dependency versions to ease downstream auditing.