# Design

## Evidence and boundaries

Workspace acceptance run 4 (`35866135023`) records two moderate and three high package findings. DOMPurify's IN_PLACE/removal-hook advisory has conditions not used by the current string-sanitizing FileViewer. The cited Vite advisory concerns network-exposed Windows development servers. Upgrade conservatively without equating an audit finding to demonstrated application exploitability.

## Candidate then committed verification

The local execution container has no working external DNS. A read-only pull_request runner therefore performs npm's targeted resolution for DOMPurify, Vite, devalue, nanoid and PostCSS. It retains candidate package.json/package-lock.json, their diff and exact test/audit logs. Candidate resolution is explicitly temporary bootstrap machinery, not a committed-lock security gate. No CI job has contents-write permission or publishes changes.

The implementer inspects the candidate's package additions/removals, major compatibility, optional platforms and integrity metadata before copying the exact files into the topic branch. Replace the bootstrap with clean npm ci plus fail-closed npm audit before marking implementation complete. Ordinary acceptance runs against the committed files, not an uncommitted audit-fix workspace.

No npm audit fix --force, advisory ignores or unsafe parser/sanitizer replacements. Registry/network/audit errors fail verification rather than being interpreted as zero findings. New unrelated advisories are evaluated explicitly.

## Compatibility and review

Existing dependency major lines remain unchanged. Existing frontend tests, Svelte/TypeScript checks, production build, real Vite proxy tests and Chromium/FastAPI smoke protect compatibility. Runtime markdown sanitization remains enabled; no application rendering or authority logic changes.

Tooling is isolated outside application dependencies. OpenSpec strict validation covers both this change and workspace-status-resilience. GitNexus indexes only in the disposable runner, with no embeddings, model calls, generated agent instructions or publishing. Retrospective impact/detect-changes output is reviewed alongside the actual git diff; UNKNOWN, partial or truncated output cannot be called a complete clean gate. No production functions are edited by this task.
