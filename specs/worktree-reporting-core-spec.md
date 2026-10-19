# Worktree reporting core — implementation specification

Status: **private implemented contract for package review**, 2026-10-19. Private implementation and first-party MIT preparation were selected by the rights holder. Publication and runtime adoption remain unapproved. The command/package names and recommended destinations have been selected for private preparation; this does not authorize publication.

## Outcome and vocabulary

A developer selects local Git repositories and receives an attributable report of their registered worktrees and overlapping uncommitted paths. Every selected repository and registered worktree is accounted for, or the report explicitly states that coverage is incomplete. The report helps a developer coordinate code work. It does not prevent writes, fence another process, prove a merge safe, or authorize a task/action.

Canonical terms:

- **Selection:** the explicit repository roots supplied for one invocation. No implicit home, current-directory repository, estate fleet or filesystem-root discovery.
- **Repository:** one Git common directory, shared by its registered worktrees. Separately cloned repositories are distinct, even when they share a remote or commit history.
- **Worktree:** a checkout registered to that repository, including its main checkout. Registration is not proof that its directory is accessible.
- **Dirty path:** a repository-relative path reported by the supported Git status observation. It is not an agent/session identity, file-content comparison or committed-branch diff.
- **Overlap:** an exact dirty-path identity observed in two distinct worktrees of the same repository. It is an observation, not a prediction of semantic or merge conflict.
- **Complete coverage:** all selected repositories were discovered and all their registered worktrees were observed within the supported features and limits, without detected drift. It is not an atomic filesystem snapshot or proof that no intervening change happened.

Do not use the old helper's “session”, “active/stale”, “conflict” or “removable” labels for these concepts. A worktree does not establish who is using it or whether its branch can be deleted.

## Module interface and test seam decision

The installed command is the sole supported integration seam. The Python import layout is private implementation detail in v0.1. A small internal Git adapter contains command execution and byte parsing; a report module owns coverage and overlap semantics. No shared Orion SDK, daemon, persistent cache, task database or schema service is introduced.

The primary acceptance seam is **the installed CLI invoked against disposable real Git repositories**. The same invocation is used by readers, future harness recipes and tests. A test-controlled Git executable wrapper supplies bounded failures or changes only to owned fixtures; narrow parser tests supplement malformed byte streams. This avoids making a parallel test-only reporting interface the evidence for the user outcome.

Every scenario below is a complete invocation through selection, Git observation, coverage calculation, result rendering and exit status. Build the scenarios sequentially, one RED→GREEN cycle at a time.

## Supported invocation

Working command:

```text
orion-worktree-report [--json] version
orion-worktree-report [--json] scan --repo ABSOLUTE_CHECKOUT_ROOT [--repo ABSOLUTE_CHECKOUT_ROOT ...]
orion-worktree-report --help
```

`scan` requires at least one absolute checkout root, including an explicitly selected linked worktree root. Each supplied root is limited to 4,096 raw bytes; empty, relative or overlong root arguments are invalid invocation. A path inside a checkout is not silently promoted to its parent. Canonicalize filesystem aliases and deduplicate selections by Git common-directory identity; record each input's resolution or problem. No recursive directory scanner or private PM reader is present.

Only these operations exist. Cleanup/apply, prune, repair, linking, merge preview, automatic fetch, remote lookup and task acquisition are not alternate flags or hidden subcommands. Unknown options/subcommands are invalid invocation, not ignored input. The command writes its report to stdout; saving it is the caller's explicit redirection, not an in-repository output option.

Default text and `--json` convey the same coverage, conclusion and problems. Text is for reading, JSON is the machine contract. A consumer must check the interface version, coverage and conclusion; a parsed object alone establishes neither complete coverage nor absence of overlap.

## Selection, observation and supported repositories

Install into a dedicated virtual environment with its own `bin/python`. The POSIX command launcher starts that interpreter with bytecode writing disabled before startup; system/user-prefix installs without that interpreter are unsupported. The initial proof target is CPython 3.11, Linux x86_64, local ext4 and Git 2.43.0. Git older than 2.43 is unsupported. Other versions/platforms remain unverified until entered into the release's actual acceptance matrix; the wheel's generic Python tag does not establish Windows/macOS or network-filesystem support.

Use Git's NUL-delimited registered-worktree output, rather than a guessed directory depth. Include locked and missing/prunable registrations in coverage. Do not prune or repair them. Reject bare selections as unsupported; a normal checkout with an unborn branch can be observed and must identify its unborn HEAD explicitly. Detached HEAD is a valid observation, not a failed branch lookup.

Observe staged and unstaged paths and individual nonignored untracked files. Ignored paths, committed-only divergence and submodule interiors are excluded. The initial release refuses repositories with submodules/gitlinks, sparse checkout/index, split index, partial/promisor clones, included repository configuration, configured content filters or other unsupported read effects. Refusal is visible coverage, never a clean empty result. No opt-in unsafe mode is shipped.

The ignore/attribute policy is **repository-only**: disable global/system config and attribute files, retain the selected repository's own ignore rules and report this policy in the result. Do not read account/credential helpers or report remotes, configuration values, file contents, diffs, process tables or private agent state. Before any repository-aware Git setup, resolve the selected checkout's Git directory and common directory from bounded metadata (at most 4,096 bytes per pointer), and read at most 1 MiB of selected configuration in aggregate. Parse only those bounded snapshots with includes disabled, outside repository discovery. Refuse include/includeIf declarations before their targets are opened. Preserve main and linked-worktree support, including worktree-specific configuration. Compare configuration and pointer fingerprints across observations. Never print configuration values or Git's raw stderr.

A repository changing during observation is cooperative concurrent state, not an adversarial isolation problem. Compare normalized registration lists before/after, and each worktree's HEAD/branch identity, index digest, supported configuration fingerprints and normalized status before/after. Any observed mismatch makes that scope `changed` and coverage partial/unavailable. Do not silently retry until a favorable answer appears. Identical samples cannot rule out change-and-revert between samples; no atomic snapshot or hostile same-user protection is claimed.

## Exact path and overlap semantics

Parse NUL-delimited porcelain status as bytes. Do not split status on newlines/arrows, trim path whitespace, decode with replacement, normalize case, or Unicode-normalize identities. Dirty paths must be relative with no empty, `.` or `..` components; absolute/traversing/malformed status paths refuse that observation rather than becoming filesystem reads.

- Paths carry `path_b64`, standard padded Base64 of the original relative path bytes. That is the canonical identity used for comparison and structured encoding.
- `path_utf8` contains the exact string only when the bytes are valid UTF-8; otherwise it is null. Render control characters escaped in text/JSON. A display label is never the identity.
- For an indexed rename/copy record, retain both reported path roles and include both in the worktree's dirty-path set. This conservatively detects another worktree touching either side; report each exact shared path once for each unordered worktree pair.
- Untracked files are enumerated individually under the same limits. Ignored paths are absent by the declared scope. Unmerged entries are dirty paths, not merge authority or an instruction to resolve them.
- Preserve absolute repository/worktree paths using the same byte-safe representation. Reports contain local path names and are not automatic public/redacted artifacts.
- Repository/worktree/overlap IDs are opaque, locally stable hashes of canonical, domain-tagged, length-unambiguous identities. Never concatenate raw names with an ambiguous delimiter. IDs are not secret, portable across machines, actors, leases or permission tokens.

Order repositories/worktrees/paths by their canonical raw-byte identities, and overlap pairs by those IDs and raw paths. Input aliases/order do not duplicate observations. No age/urgency ranking, incident suppression store, proximity score or persistent event feed exists.

## Coverage, conclusions and exits

Registered worktree totals are null if discovery failed for any selected repository; do not invent zero. Counts distinguish discovered, successfully observed and unavailable scopes. Each unavailable/changed/unsupported/limited scope has a stable reason code. Known positive overlaps may be retained from successfully observed scopes in a partial report, explicitly as a subset.

`repositories_selected` counts unique resolved repository identities plus distinct unresolved supplied roots; aliases of one discovered repository count once. The eight-root invocation cap counts supplied arguments before this deduplication. `worktrees_unavailable` counts known registered scopes not successfully observed; unknown registrations from a discovery failure are represented by the null total and selection problem, not fabricated unavailable rows.

| Coverage | Conclusion | Exit | Meaning |
|---|---|---|---|
| `complete` | `no_overlap_observed` | 0 | Every selected scope observed; no exact dirty-path overlap in those observations. |
| `complete` | `overlap_observed` | 1 | Complete coverage and one or more observed overlaps. |
| `unavailable` | `indeterminate` | 2 | Invalid invocation; scan not accepted. |
| `partial` | `overlap_observed` or `indeterminate` | 3 | Some usable observations, but coverage is incomplete. Never `no_overlap_observed`. |
| `unavailable` | `indeterminate` | 4 | No usable supported observation, output cannot be represented within limits, or required Git capability unavailable. |
| `unavailable` | `indeterminate` | 70 | Internal contract failure; bounded generic error, no traceback or false success. |

Partial status takes precedence over the complete-scan overlap exit. Missing Git, command failure, parse error, unsupported repository features, inaccessible/missing checkout, observed change and exceeded bounds are distinct reason codes. No command failure is swallowed into an empty list. A discovery failure in one selected repository cannot erase successful observations of another.

JSON is one complete UTF-8 object plus one LF, generated before writing stdout. It contains `interface_version: 1`, `package_version`, `command`, `scan_id`, UTC start/finish times, `authority: "none"`, `scope: "registered-worktrees/dirty-paths"`, `ignore_policy: "repository-only"`, input resolutions, repository/worktree facts, overlaps, coverage/counts/problems and the exit integer. Cross-field invariants enforce the table above. `scan_id` correlates this observation only; it provides no idempotency or action authority. `version` emits a separate bounded version/capabilities object and exits 0 without repository access.

Normative field shape is illustrated by the [contract examples](../tests/fixtures/contract-examples.json). The examples are design fixtures, not execution receipts. Common path objects have exactly `path_b64` and `path_utf8`. A scan uses `inputs`, `repositories`, `worktrees`, `overlaps`, `coverage` and `problems` arrays/objects at the top level; `coverage` has `status`, `repositories_selected`, `repositories_discovered`, `registered_worktrees`, `worktrees_observed` and `worktrees_unavailable`. `conclusion` and `exit` are top-level fields. There is no overloaded `ok` field.

Repository rows have `repository_id`, `common_directory` and `discovery_state`. Worktree rows have `worktree_id`, `repository_id`, `root`, `observation_state`, `head`, `dirty_paths` and `renames`. A successfully observed `head` distinguishes commit/unborn and carries nullable branch bytes; a detached commit has no branch. `renames` carries source/destination path roles and rename/copy kind. Unobserved `head`, `dirty_paths` and `renames` are null, never a fabricated clean array. Overlap rows identify one repository, a sorted unordered pair of worktree IDs, one exact path and an opaque ID. Problems identify scope, nullable affected IDs and one stable category. Input rows preserve supplied paths, the resolved repository ID or null, and `problem`: null for a resolved input or a stable code plus optional fixed feature for that input. This explicit association also survives an invocation-wide Git capability failure. No raw diagnostics or additional incidental Git fields enter interface v1 by accident.

Problems contain stable categories and affected opaque identities, not raw Git stderr, config commands, remote URLs or secret values. Stderr may contain a bounded generic diagnostic. Broken output pipes exit unsuccessfully; no second JSON result is appended. If final serialization exceeds the output cap, emit a small `output_limit` unavailable envelope with empty fact arrays and indeterminate conclusion, rather than silently truncating a successful result. Empty arrays in that envelope do not mean an empty scan.

Interface-v1 problem categories are: `invalid_invocation`, `git_missing`, `unsupported_git_version`, `repository_unavailable`, `checkout_unavailable`, `git_failed`, `git_timeout`, `command_output_limit`, `status_parse_error`, `state_changed`, `worktree_limit`, `path_limit`, `overlap_limit`, `index_limit`, `config_limit`, `scan_deadline`, `output_limit`, `internal_error`, and `unsupported_repository_feature`. The last category carries one additional fixed `feature` value from `bare`, `content_filter`, `included_config`, `submodule`, `sparse`, `split_index`, `partial_clone`, or `unproven_read_effect`. That optional field is absent for other categories. No unrecognized feature is treated as supported by default.

Fixed v0.1 limits, not tunable bypasses: 8 supplied roots, 64 registered worktrees, 4,096 dirty path identities per worktree, 1,000 overlap records, 2 MiB captured stdout per Git command, 64 KiB captured stderr per command, 128 MiB index fingerprint input per worktree, 1 MiB selected repository configuration input, 1 MiB final JSON, 5 seconds per Git command and 60 seconds for the invocation's own scan deadline. Git children are owned process groups with bounded concurrent pipe draining; stop/reap that group on timeout/overflow. Do not kill unrelated Git or agent processes. Host scheduling/uninterruptible I/O cannot have a hard wall-clock guarantee.

Limits are checked before treating the affected scope as complete. Too many roots is exit 2. Any other cap makes affected coverage partial, or unavailable when no usable observations/final result can be represented. The overlap cap must be detected as overflow, not a silently truncated list. Fallback envelopes remain below 16 KiB, including bounded input/problem identifiers; they never echo unrestricted arguments.

## Reporting-only effect contract

The supported command initiates no writes to selected repositories' objects, refs/reflogs, index/shared index, configuration, tracked/untracked working files or worktree registrations. It creates no lock/cache/report file in selected repositories. The contract excludes ordinary filesystem access-time accounting and external concurrent changes; it is not a sandbox against hostile repositories, Git executables, plugins or same-user actors.

The reader checks bounded index headers, checksums and extensions directly before any Git index-reading command, refusing split/sparse or unknown mandatory extensions without opening their shared index. Native SHA-1/SHA-256 index versions 2, 3 and 4 have explicit acceptance cases.

The effect contract requires a trusted executable and stable cooperative repository configuration for the invocation. A preflight cannot prevent another actor substituting configuration afterward. Refuse detected drift and report incomplete coverage; do not claim containment of a concurrent configuration writer. Read-only mounts/process sandboxing or a hard configuration lock are not introduced by v0.1.

Resolve the Git executable once, use argv with no shell interpolation, close stdin, disable pager/prompts/optional locks, scrub inherited Git redirection/config/trace variables, disable fsmonitor, hooks, lazy/object fetching and attribute/filter execution as supported by the selected Git. Repository-feature preflight must happen before any status operation that could execute a driver. On the initial Git target, configurations whose safe read effects cannot be established are refused, not silently disabled while claiming original semantics. Do not override ownership trust checks or edit `safe.directory`.

No Git command may acquire/create/repair/prune a worktree, write a tree object, update an index/ref/config, invoke an external merge/diff/filter/helper, contact a network service or retry an uncertain mutation. The internal command catalog and selected environment are verified through execution traces and native sentinels in addition to output assertions. If the effect contract cannot be proven for the supported target, the release remains private.

## End-to-end scenarios and acceptance criteria

**S1 — Select and account.** A caller selects an ordinary repository through its main root and a linked-root alias. The report deduplicates that repository, includes all registered worktrees at arbitrary directory depth, and shows valid clean, detached and unborn observations without assuming a branch named `main`. Zero paths is reported as no overlap only with complete coverage. Missing/bare/relative selections have their specified refusal outcomes.

**S2 — Observe an overlap with exact identity.** Two registered worktrees dirty the same relative path; the installed report identifies one unordered pair and that path. A third unrelated clone with the same path does not join the pair. Spaces, tabs, newlines, literal arrows, leading dashes, non-ASCII and non-UTF-8 bytes retain exact identities. Indexed rename roles, untracked files, deletion and unmerged paths behave as specified. Reordering inputs does not duplicate facts or overlaps.

**S3 — Preserve uncertainty.** One checkout's metadata is unavailable, status output is malformed, a command fails, times out or exceeds a cap, or repository registrations/index/status/config change between samples. Remaining valid observations remain attributable; no missing scope becomes clean absence. Partial and unavailable results use the exit table and strict structured envelope, and no raw error/config text leaks. All scopes unavailable yields no positive/negative conclusion beyond indeterminate.

**S4 — Prove the read effects.** On the supported platform the installed scan leaves selected fixture metadata and content byte-identical and creates no new objects/locks/cache/registration. A configured clean-filter sentinel, fsmonitor sentinel, Git trace target and network/credential sentinel remain uninvoked/unwritten. Unsupported features refuse before a hazardous status command. Inherited `GIT_DIR`, index/object redirection, tracing or config injection cannot redirect the scan or create files. No mutation/preview/link subcommand is available. Report generation can only write stdout/stderr.

**S5 — Install and consume the reviewed release.** Inspect wheel/sdist contents, install each selected artifact in separate clean environments, run S1–S4 through the actual installed command, and reproduce the standalone quickstart using synthetic repositories. Record exact hashes, tool/platform versions and test scope. A caller can validate the report and retain it deliberately as evidence without granting PM ownership or modifying another package. Uninstall removes package files only and preserves caller repositories/reports. The source/site/guide packet states demonstrated support and known exclusions accurately.

S1–S5 are the acceptance reference for package review and a later implementation PR. Passing the private helper's existing unit suite, a mocked runner or a local source invocation alone does not satisfy them. Execution evidence and exact artifact bindings are recorded separately; this document defines the acceptance criteria.

## Ecosystem and release boundary

PM continues to own claims and guarded task/evidence operations; browser/phone own their resource leases; Handoff owns its records; Results owns selected captured data. This report has no mandatory dependency on them. A future caller adapter may save a report and attach its digest, observation time and scope using PM's sanctioned interface. It may not write PM stores directly or convert observed overlap/absence into authority. No native Claude/Codex/Grok/Dot support or starter-profile compatibility follows from a generic CLI proof.

Prepare the source/license/notices, exact artifact allow-list, clean-install receipts, quickstart, recovery/uninstall guide, Works microsite and canonical guide for a later full private review. Rights, historical ECC provenance, final names/license/destinations, source gates and actual outward actions remain explicit release decisions. Videos retain their own creative review. Private estate helpers, agent configurations and current public package/starter pins remain unchanged.

## Installation verification

Create reporter environments without bundled pip/setuptools. A checksum-pinned external installer installs only the inspected local wheel with no index/dependencies. Source acceptance uses the exact reviewed tool lock and records actual versions. The installed environment contains only the reporter; removal through the same external installer preserves repositories, worktrees and saved reports.
