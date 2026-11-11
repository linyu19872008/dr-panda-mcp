## What changed

<!-- Describe the change and why it is needed. -->

## Verification

- [ ] `uv run pre-commit run --all-files` (or hooks installed via `uv run pre-commit install`)
- [ ] `uv run ruff check .`
- [ ] `uv run pytest -q`
- [ ] `uv run python scripts/check_docs_links.py`
- [ ] `uv run python scripts/build_pypi_readme.py --check`
- [ ] If `alembic/versions/` changed: `uv run python scripts/integration/check_db_setup.py`
- [ ] Manually verified user-visible behavior (describe how)

## Read-only / security impact

- [ ] No new write operation, credential exposure, or read-only boundary change
- [ ] If security-related, I did not disclose unfixed details publicly

## Docs

- [ ] README / user docs updated
- [ ] English and Chinese versions updated together when applicable
- [ ] If `README.md` changed: `README.pypi.md` regenerated (do not edit by hand)

## Notes

<!-- Known limitations or follow-ups. -->
