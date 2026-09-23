## ADDED Requirements

### Requirement: Reproducible patched dependency resolution
The frontend SHALL use a reviewed npm-generated lock that resolves the observed affected dependencies within existing major compatibility ranges and retains authentic registry integrity metadata.

#### Scenario: A candidate resolution is generated remotely
- **WHEN** a read-only runner generates a candidate manifest and lock
- **THEN** the diff and exact candidate files are retained for review
- **AND** no repository write or deployment occurs automatically

### Requirement: Fail-closed dependency audit
The committed dependency set SHALL pass npm audit during clean-install verification; unavailable or malformed audit results SHALL be treated as failures rather than clean results.

#### Scenario: The audit detects a vulnerability or cannot run
- **WHEN** npm audit returns findings, a registry error or invalid output
- **THEN** the dependency gate fails and retains diagnostic evidence

### Requirement: Preserve existing application behavior
Dependency hardening SHALL preserve the graph-native UI, server authority, runtime sanitization and existing API transport behavior.

#### Scenario: The reviewed lock is committed
- **WHEN** verification installs dependencies using npm ci from that lock
- **THEN** frontend tests, type checks, build and existing Chromium/FastAPI acceptance are executed against the committed candidate
- **AND** skipped, partial and unexecuted checks remain explicitly distinguished from passing checks
