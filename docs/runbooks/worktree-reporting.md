---
verified: 2026-10-19
review_after: 2026-11-19
topics: [git, worktrees, reporting, local-cli]
references:
  - README.md
  - specs/worktree-reporting-core-spec.md
  - src/orion_worktree_report/git_read.py
  - tools/verify_release.py
---

# Run a bounded worktree observation

## Rollout and prerequisites

Install the reviewed wheel into a dedicated virtual environment with its own bin/python using the README. The POSIX launcher starts Python with -B before startup so cold imports cannot create bytecode caches in a selected repository. Other installation layouts are unverified. No service, timer, hook, daemon, Git configuration change or package integration is installed. Use only the declared acceptance target. The executable on PATH must be trusted; configuration must remain cooperative and stable. Keep Git ownership checks intact. Never add a safe.directory bypass to make a refused repository pass.

Select up to eight absolute checkout roots explicitly. Roots must be checkout roots, not arbitrary subdirectories. All registrations of each selected repository enter coverage, including locked and missing/prunable worktrees. Aliases deduplicate by common directory; clones remain distinct. The scope is uncommitted dirty-path observations, not branch divergence or semantic merge safety.

## Validate and retain

Run `orion-worktree-report --json scan --repo /absolute/checkout` and save stdout only to a caller-selected path outside the selected repositories. Check interface version 1, process exit, coverage, conclusion and problems together. Exit 1 means a complete positive observation. Exit 3 never establishes no overlap. A null total means discovery was incomplete. Null dirty paths mean the checkout was not observed.

The Git adapter disables optional locks, fsmonitor, global/system configuration/attributes/ignore files, hooks, prompts and inherited Git redirection/tracing. Repository-local ignore rules still apply. Filters, includes, submodules, sparse/split indexes and partial/promisor clones refuse before status. Index assume-unchanged/assume-valid, skip-worktree and unknown extended flags also refuse as `unproven_read_effect`; the reporter does not clear those flags or interpret hidden paths as clean. Intent-to-add remains observable. The lazy-fetch environment flag is defense in depth, not a compatibility assumption; partial clones are refused on Git 2.43. No network operation is part of the command catalog.

## Monitoring and failure interpretation

Observe each explicit invocation. No recurring monitor is created. Problems are stable categories without raw Git stderr or config values. Consult the spec for the full category list. Repair environment or repository issues independently under their own authorization; the reporter does not repair/prune/retry them.

Fixed limits: eight root arguments, 4,096 bytes/root, 64 registrations, 4,096 dirty paths/worktree, 1,000 overlaps, 2 MiB Git stdout, 64 KiB Git stderr, 128 MiB index input/worktree, 1 MiB aggregate selected configuration input/worktree, 1 MiB final output in either JSON or text, five seconds/Git command and a 60-second owned scan deadline. Any exceeded cap removes complete coverage. The final output fallback is a small unavailable result; empty arrays in it are not clean observations. Child groups are stopped on failure/overflow; unrelated processes are not targeted. Uninterruptible I/O and host scheduling have no hard wall-clock guarantee.

Two samples compare registrations, HEAD, index/config digests and status. Drift invalidates that scope without silent retry. A change-and-revert between reads may escape detection. This is cooperative observation, not fencing or containment of concurrent configuration substitution.

## Privacy

Local paths and branch names can be sensitive. Saved reports are not public receipts. Review/redact them before sharing. Keep byte identities separate from display labels. File contents, diffs, remote URLs, secrets and process/task state are not collected into reports. Do not enable trace logging or raw diagnostics to work around an unavailable result.

## Rollback and removal

Uninstall from the dedicated environment. No runtime state, repository metadata, report store or cache requires migration. Preserve caller reports and workspaces. A later consumer integration needs its own reviewed rollout/rollback. After first publication, corrections require a new reviewed version; never silently replace published assets. Before publication, retain replaced candidates and bind any accepted replacement to its exact checksums.

## Installer scope and configuration preflight

Use the README's checksum-pinned external installer with targets created using `venv --without-pip`. Never fall back to bundled installer versions or upgrade global tools as part of this check. The verifier checks the exact acceptance-tool lock and records the actual versions; its installed seam requires the reporter to be the only target distribution. Keep the external installer for uninstall. Installer files are user-selected setup files outside the selected repository; scans do not execute it. Native tests require strace.

Configuration preflight resolves bounded Git pointer metadata directly, then inspects bounded configuration snapshots without following include targets or discovering a repository. Native tests trace main, linked and worktree-specific include refusals from inside the selected checkout. This is cooperative read-scope validation, not hostile-concurrent-configuration containment.
