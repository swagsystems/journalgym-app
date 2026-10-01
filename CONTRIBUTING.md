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

## Backend dependency updates

Keep `requirements.txt` and its hashed lockfile together. After changing a direct
dependency, regenerate the lockfile using Python 3.12:

```bash
uv pip compile --generate-hashes --output-file requirements.lock requirements.txt
python -m pip install --require-hashes -r requirements.lock -r requirements.txt
```

CI and Docker install both files in one resolver invocation. Conflicting direct
pins fail resolution, and missing locked dependencies fail hash validation, so a
manifest-only update cannot silently test or ship the old version.
