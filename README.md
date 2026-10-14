# Pharma Intelligence OS Next

Original private development core for durable evidence-linked cases and independent human review.

Implemented: tenant-scoped SQLite case/revision storage, optimistic version checks, authenticated editor/reviewer roles, reviewer separation, reviewed-case JSON working-draft export with SHA-256, transactional audit events. No AppDeploy runtime dependency.

Install with `python -m pip install -e '.[test]'`; run `python -m pytest -q`.
Start with `uvicorn pharma_next.main:application --factory`; supply PHARMA_SERVICE_IDENTITIES as a JSON mapping of strong bearer tokens to tenant/subject/role, through protected environment injection. Do not paste or commit credentials. Set PHARMA_DATABASE to a persistent database path.

Use `/docs` for the API; authenticated `/v1/cases` endpoints create/read/revise/history/review/draft. `/health` describes process status only. TLS termination and credential rotation are deployment requirements.

This is a working-draft workspace, not a regulatory submission system. E2B schema validation, real source ingestion, statistical signals, OIDC, encryption at rest, externally anchored audit integrity, operational UI and six-service integration remain pending. Docker configuration exists; container build has not yet been verified.
