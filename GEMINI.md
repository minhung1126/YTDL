# GEMINI.md

## Development & Release Conventions

This document outlines the development and maintenance workflow for this project.

### 1. Version Management

- **File**: `YTDL.py`
- **Variable**: `__version__`

The project version is managed solely by the `__version__` variable in `YTDL.py`.

- **Development Environment**: Automatically detects `.gitignore`. If present, `__version__` is set to `"dev"` to skip update checks.
- **Release Version**: Update `__version__` to `v{yyyy}.{mm}.{dd}.{index}` (e.g., `"v2026.01.20"`) before pushing to `main`.

### 2. CI/CD Release Flow

- **Workflow**: `.github/workflows/auto-release.yml`

Automated via GitHub Actions:
1. Pushing a new tag (e.g., `v2026.01.20`) triggers the workflow.
2. The workflow reads `__version__` from `YTDL.py`.
3. Creates a GitHub Release with that tag.

### 3. User Update Process

- **Trigger**: Launching `YTDL.py` or `YTDL_mul.py`.
- **Handler**: `self_update.py`

Seamless update mechanism:
1. Checks GitHub for newer releases on startup.
2. If found, downloads and runs `self_update.py`.
3. Updates script files (`YTDL.py`, etc.).
4. Enforces binary versions (`yt-dlp`, `deno`) as defined in the **new** `YTDL.py`.
5. Restarts the original script.

### 4. Dependency Management

- **Python Packages**: Installed at runtime using `subprocess` if `import` fails (friendly for non-devs).
- **Binaries (yt-dlp, deno)**: Versions are pinned in `YTDL.py`. `self_update.py` enforces these versions during updates to ensure stability across all users.