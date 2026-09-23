## 1. Explore and resolve
- [x] 1.1 Read actual audit output and primary advisory conditions.
- [x] 1.2 Record bounded ownership, compatibility and non-goals before dependency edits.
- [x] 1.3 Generate candidate manifest/lock with npm and inspect the complete diff.

## 2. Implement
- [x] 2.1 Commit the exact reviewed manifest/lock.
- [x] 2.2 Replace bootstrap resolution with clean-install, fail-closed dependency audit.
- [x] 2.3 Add a disposable real-FileViewer Markdown safety regression without production hooks.

## 3. Verify and deliver
- [ ] 3.1 Verify committed-lock audit, frontend tests/check/build.
- [ ] 3.2 Run existing Chromium/FastAPI/backend acceptance and new FileViewer safety checks on the committed candidate.
- [x] 3.3 Execute OpenSpec/GitNexus tooling and record limitations without waiving incomplete gates.
- [ ] 3.4 Publish exact committed-candidate evidence and final diff review; preserve outstanding parent acceptance.

Candidate run 35867416702: audited dependency set has zero findings, 60 frontend tests pass, check/build pass. This is candidate evidence, not committed-lock acceptance. Exact lock Git blob is `4f298fb0aacf6846647e1d5aa906f4dd30fb72e3` (verified byte-for-byte after upload).

OpenSpec strict passed for both changes. GitNexus runs 35867416702 / 35867815444 executed indexing/impact/detect-changes; Svelte lookup remains incomplete, risk UNKNOWN, so the parent GitNexus gate is NOT marked complete. See review.md.
