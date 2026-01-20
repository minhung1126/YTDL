# GEMINI.md

## Development Conventions

### 1. Versioning
- **Source**: `YTDL.py` -> `__version__`
- **Format**: `v{yyyy}.{mm}.{dd}.{index}` (e.g., `v2026.01.20`)
- **Dev Mode**: Auto-set to `"dev"` if `.gitignore` exists.

### 2. Releases
- **Trigger**: Push a tag (e.g., `git tag v2026.01.20 && git push origin v2026.01.20`).
- **Automation**: GitHub Actions creates a release from the tag.

### 3. Dependencies
- **Python**: Install at runtime via `subprocess` on `ImportError`.
- **Binaries**: Update via `self_update.py` (versions pinned in `YTDL.py`).

### 4. Environment
- **OS**: Windows 11
- **Shell**: Command chaining preferred. Ensure correct symbols used (`&&` vs `;` depending on shell).