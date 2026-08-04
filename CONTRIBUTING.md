# Contributing

Keep changes focused, tested, and documented.

## Verification

```bash
python -m unittest discover -s tests
python -c "import api.main"
cd frontend
npm ci
npm run test:drafts
npm run test:bulk
npm run build
```

Update the README when setup, environment variables, deployment behavior, or user-visible features change. Do not commit runtime data, SQLite databases or sidecars, local `.env` files, `frontend/dist`, dependency directories, or Python bytecode.
