# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Dockerfile with multi-stage build, non-root user, and base image digest pinning
- Security scanning in CI (trivy for container, npm audit for dependencies)

### Changed
- Hardened Dockerfile: non-root user (UID 1000), base image digest pinning, multi-stage build

### Security
- Added non-root user (UID 1000) in Dockerfile
- Pinned base image digests
- Added security audit steps in CI

## [0.1.0] - 2026-09-30

### Added
- Pharmacovigilance & regulatory intelligence workspace
- ICSR review with human verification
- ICH E2B(R3) packages
- PRR/ROR signal management
- PSUR/PBRER drafts
- FDA approval tracking
- React 19 + TypeScript + Vite + Tailwind CSS
- ESLint + TypeScript ESLint + Vitest
- GitHub Pages deployment workflow

---

**Full Changelog**: https://github.com/we-do-care-global/pharma-intelligence-os/commits/main