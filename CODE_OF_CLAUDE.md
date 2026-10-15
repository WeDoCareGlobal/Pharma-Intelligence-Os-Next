# CODE_OF_CLAUDE.md

This file defines the conventions and expectations for AI-assisted coding in pharma-intelligence-os.

## AI Agent Conventions

### When AI agents (Claude, Codex, etc.) work on this repository:

1. **Follow the existing patterns** — Read existing code before writing new code. Match the style, structure, and conventions already present. This is a React/TypeScript/Vite project.

2. **Write tests first** — Every new feature or bug fix must include tests. Target ≥80% coverage.

3. **Run the full CI locally before pushing** — Execute:
   ```bash
   npm ci
   npm run lint
   npm run typecheck
   npm run test
   npm run build
   ```

4. **Update documentation** — If you change behavior, update:
   - `CHANGELOG.md` (under `[Unreleased]`)
   - Relevant docstrings and README sections
   - Component documentation

5. **Use conventional commits** — Prefix commits with:
   - `feat:` new feature
   - `fix:` bug fix
   - `docs:` documentation only
   - `refactor:` code change that neither fixes a bug nor adds a feature
   - `test:` adding or modifying tests
   - `chore:` maintenance (deps, config, etc.)

6. **Security first** — Never commit secrets. Use environment variables for configuration. Run security scans (npm audit, trivy) before merging.

7. **Docker best practices** — When modifying Dockerfile:
   - Use specific base image digests (not tags)
   - Run as non-root user
   - Multi-stage builds for smaller images
   - No secrets in images

8. **Observability** — Consider adding metrics for new API endpoints if backend is added.

9. **Regulatory compliance** — This is a pharmacovigilance system. Changes to ICSR, E2B, signal management, or regulatory tracking must:
   - Maintain strict data integrity
   - Include audit trails
   - Follow ICH E2B(R3) standards

10. **No silent failures** — All errors must be logged and surfaced appropriately. Use proper error boundaries in React.

## Code Review Checklist for AI Contributions

- [ ] Tests added and passing (≥80% coverage)
- [ ] Linting passes (ESLint)
- [ ] Type checking passes (tsc --noEmit)
- [ ] Security scans pass (npm audit, trivy)
- [ ] CHANGELOG.md updated
- [ ] Documentation updated
- [ ] No hardcoded secrets
- [ ] Dockerfile follows best practices
- [ ] Conventional commit messages

## Prohibited Patterns

- ❌ `console.log()` for logging (use proper logging library)
- ❌ Bare `catch {}` clauses
- ❌ Hardcoded paths, URLs, or credentials
- ❌ Skipping tests to "make CI pass"
- ❌ Adding dependencies without updating package-lock.json
- ❌ Modifying generated files (dist/, build/)
- ❌ Committing directly to `main` (use PRs)

## Escalation

If an AI agent encounters ambiguity or conflicting requirements:
1. Stop and ask the human maintainer
2. Document the question in the PR description
3. Do not guess — clarify first

---

**ORCID**: 0009-0009-8515-2727 (Emir Perla)
**Maintainer**: We Do Care Global