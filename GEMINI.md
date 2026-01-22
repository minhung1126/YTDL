# GEMINI.md

## Development Conventions

### 1. Versioning

- **Source**: `YTDL.py` -> `__version__`
- **Format**: `v{yyyy}.{mm}.{dd}.{index}` (e.g., `v2026.01.20.01`)
- **Dev Mode**: Auto-set to `"dev"` if `.gitignore` exists.

### 2. Releases

- **Trigger**: Push a tag (e.g., `git tag v2026.01.20.01 && git push origin v2026.01.20.01`).
- **Automation**: GitHub Actions creates a release from the tag.

### 3. Dependencies

- **Python**: Install at runtime via `subprocess` on `ImportError`.
- **Binaries**: Update via `self_update.py` (versions pinned in `YTDL.py`).

### 4. Environment

- **OS**: Windows 11
- **Shell**: PowerShell. Run commands sequentially. Do NOT chain commands (e.g. with `;` or `&&`) as this prevents auto-continue from triggering.

### 5. Quality Assurance

- **Syntax Check**: Always check for syntax errors before every commit (e.g., `python -m py_compile <file>`).
