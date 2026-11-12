# Pre-Release Consolidation Baseline — Pharma-Intelligence-Os-Next

## Issue Reference
- Issue #2: "Pre-release: original-code consolidation and 10-step completion plan" (open)
- Acceptance: All required tests on exact candidate SHA; no mocked success, undocumented skipped integrations, exposed credentials, missing attribution, or unproven product claims. Preserve donor repositories; adapt selected modules on development branches. No public release or production deployment in this planning task. OmniGuard remains excluded.

## Baseline SHAs (from issue)
| Reference | SHA | Description |
|-----------|-----|-------------|
| Baseline | 92dcb21 | Implement durable tenant-scoped case review and working-draft export |
| Current HEAD | cbfa634 | Resolve merge conflict in PR #4: frontend/package.json lint script |

## Delta
- Commits ahead of baseline (92dcb21): 29

## Step 1 Status: IN PROGRESS
**Task:** Zaključati 92dcb21 baseline i ograničiti prvi release na evidence/review workspace; popisati nepokrivene kliničke/regulatorne funkcije.
(Lock 92dcb21 baseline and limit first release to evidence/review workspace; list unverified clinical/regulatory functions.)

**Resolution plan:**
1. Lock 92dcb21 as reviewed baseline
2. Limit first release to evidence/review workspace only
3. List unverified clinical/regulatory functions

## Source Selection (from issue)
| Source | Decision | Reason |
|--------|----------|--------|
| Original pharma-intelligence-os UI/backend | Adapt | UX and source plumbing, remove static LIVE/PRR/ROR claims |
| Private we-do-care-pharma-os/src/index.js + schema.sql | Don't copy endpoints without fix | Schema/cache/AI adapter candidates but no auth/tenant boundaries, model metadata mismatch |
| Pharma-Directory-CRM | Candidate | For UI adaptation |
| pharma UI | Candidate | For UI adaptation |

## Steps 2–10
Documented in issue #2 body. Not started.

## Verification
- [ ] Baseline documented (this file)
- [ ] Step 1: 92dcb21 baseline locked, release scope limited to evidence/review workspace, unverified functions listed
- [ ] Steps 2–10 not started
