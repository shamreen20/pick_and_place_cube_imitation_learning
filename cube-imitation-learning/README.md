# cube_imitation_learning

This folder contains a simple NOVA Python app served by FastAPI through NOVAx.

## Local Development

1. Install `uv` if not already installed:
   https://docs.astral.sh/uv/getting-started/installation/
2. Ensure `.env` is configured (`NOVA_API`, `CELL_NAME`, optional `NOVA_ACCESS_TOKEN`).
3. Run locally:

```bash
uv run python -m cube_imitation_learning
```

4. Open API docs:
   `http://localhost:8000/docs`
5. Deploy with:

```bash
nova app install
```

## Formatting

```bash
uv run ruff format
uv run ruff check --select I --fix
```