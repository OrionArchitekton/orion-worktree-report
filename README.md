# Orion Worktree Report

Part of [Cosmocrat OS](https://www.cosmocrat.ai/tools#orion-worktree-report).

Observe registered Git worktrees and exact uncommitted path overlaps in explicitly selected local repositories. Reports carry coverage and uncertainty. They grant no task ownership or permission to change files.

v0.1.0. MIT; retained ECC acknowledgment and license are in [NOTICE](NOTICE).

## Supported target

The acceptance target is CPython 3.11, Git 2.43.0 and Linux x86_64 on local ext4 under WSL2. Other Python/Git versions, Windows, macOS and network filesystems are unverified. There are no Python runtime dependencies. Install into a dedicated virtual environment with its `bin/python`; the POSIX launcher starts that interpreter with isolated imports and bytecode writing disabled before startup. System/user-prefix installs without that interpreter are unsupported. Git must be a trusted executable on your PATH and repository configuration must stay cooperative and stable for the scan.

The command refuses bare repositories, configured content filters, included repository config, submodules/gitlinks, sparse checkout/index, split index and partial/promisor clones. See the [behavior contract](specs/worktree-reporting-core-spec.md) for exact limits and the [runbook](docs/runbooks/worktree-reporting.md) for operational boundaries.

## Install the reviewed local wheel

Download the v0.1.0 wheel and SHA256SUMS from the [release](https://github.com/OrionArchitekton/orion-worktree-report/releases/tag/v0.1.0). Start in a fresh folder containing those two files. Check that the wheel's digest agrees with the release's checksum entry before installing. The [guide](https://www.danmercede.com/guides/git-worktree-overlap-report) pins the selected wheel digest directly.

Use a checksum-pinned pip as a separate installer, without relying on the Python distribution's bundled pip or setuptools. This does not upgrade global tools. Downloading the installer requires HTTPS; the actual reporter installation uses only the local wheel, with no index or dependencies.

```bash
set -euo pipefail
test ! -e .venv
test ! -e .installer
WHEEL_CHECKSUM="$(awk '$2 == "orion_worktree_report-0.1.0-py3-none-any.whl" {print}' SHA256SUMS)"
test "$(printf '%s\n' "$WHEEL_CHECKSUM" | wc -l)" -eq 1
printf '%s\n' "$WHEEL_CHECKSUM" | sha256sum --check --strict -
curl --fail --location --proto '=https' --tlsv1.2 --max-time 60 \
  https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl \
  --output pip-26.2.1-py3-none-any.whl
printf '71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e  pip-26.2.1-py3-none-any.whl\n' | sha256sum --check --strict
python3.11 -m zipfile -e pip-26.2.1-py3-none-any.whl .installer
python3.11 -m venv --without-pip .venv
python3.11 -I .installer/pip --isolated --python .venv/bin/python install --no-index --no-deps ./orion_worktree_report-0.1.0-py3-none-any.whl
.venv/bin/orion-worktree-report --json version
```

Retain `.installer` to remove the package later. The reporter environment contains only the reporter; pip and its vendored libraries live separately in this folder.

## Try two disposable worktrees

Continue in the same folder and shell. These commands create synthetic repositories only. Your Git configuration can affect fixture creation; use a fresh local test folder with ordinary Git settings.

```bash
mkdir demo-repo
git -C demo-repo init -b main
git -C demo-repo config user.name 'Synthetic example'
git -C demo-repo config user.email 'example@example.invalid'
printf 'base\n' > demo-repo/shared.txt
git -C demo-repo add shared.txt
git -C demo-repo commit -m 'Synthetic baseline'
git -C demo-repo worktree add -b worker-a ../worker-a
git -C demo-repo worktree add -b worker-b ../worker-b
DEMO_ROOT="$(pwd)/demo-repo"
.venv/bin/orion-worktree-report --json scan --repo "$DEMO_ROOT" > clean.json
printf 'worker a\n' > worker-a/shared.txt
printf 'worker b\n' > worker-b/shared.txt
OVERLAP_EXIT=0
.venv/bin/orion-worktree-report --json scan --repo "$DEMO_ROOT" > overlap.json || OVERLAP_EXIT=$?
test "$OVERLAP_EXIT" -eq 1
```

The clean command exits 0. The last command exits **1 deliberately**: `coverage.status` is `complete`, `conclusion` is `overlap_observed`, and the overlap names `shared.txt` and one pair of worktrees. An exit 1 here is a successful observation with a positive finding. The block captures and checks that exit explicitly so the walkthrough can continue under `set -e`.

Dirty paths include staged/unstaged changes and individual nonignored untracked files. Both roles of an indexed rename/copy are retained. Committed-only branch divergence, ignored files and submodule interiors are outside the scope. Separate clones are separate repositories even when their history matches.

## Read incomplete results correctly

Add one unavailable selection without altering the registered worktrees:

```bash
PARTIAL_EXIT=0
.venv/bin/orion-worktree-report --json scan --repo "$DEMO_ROOT" --repo "$(pwd)/missing-repo" > partial.json || PARTIAL_EXIT=$?
test "$PARTIAL_EXIT" -eq 3
```

This exits 3 with partial coverage. The known overlap can remain, but the registered-worktree total is null because one selection could not be discovered. A report that parses as JSON is not enough to establish complete coverage.

| Exit | Interpretation |
|---|---|
| 0 | Complete coverage, no overlap observed. |
| 1 | Complete coverage, overlap observed. |
| 2 | Invalid invocation; no accepted scan. |
| 3 | Partial coverage; positive subset or indeterminate. |
| 4 | Unavailable or exceeded final output limit; indeterminate. |
| 70 | Internal contract failure; indeterminate. |

A failed output write is also unsuccessful. Only exits 0 and 1 indicate complete coverage. Read `interface_version`, coverage, conclusion and problems together. Unobserved dirty-path arrays are null, never invented clean lists. The command performs no implicit current-directory discovery; `--repo` must name an absolute checkout root. Multiple aliases count once, with an eight-argument cap before deduplication.

## Effects, privacy and removal

On supported stable repositories, scans initiate no writes to Git objects, refs/reflogs, index, configuration, working files or registrations, and create no in-repository locks/caches/reports. Normal filesystem access-time accounting is excluded. Native inventories and sentinels test these effects; this is no sandbox against malicious Git or a concurrent configuration writer. Two matching samples are not an atomic snapshot or a lock against another developer.

Reports contain absolute local roots, branch names and relative file names. Keep them private unless you deliberately review and sanitize them. Paths use exact Base64 identities and optional exact UTF-8 labels; display strings are not identities. The reporter emits no file contents, diffs, remote URLs or raw Git errors.

Only `version`, `scan` and help exist. There is no cleanup, linking, merge preview, repair, fetch, daemon, task acquisition or automatic activation. PM, browser, Handoff and Results integrations remain separate consumer work; installation changes none of their pins or state.

```bash
python3.11 -I .installer/pip --isolated --python .venv/bin/python uninstall -y orion-worktree-report
```

Uninstall removes package files. Your repositories, worktrees and explicitly saved JSON reports remain yours.

## Development and artifact checks

```bash
# Reuse the checksum-verified .installer prepared above.
python3.11 -m venv --without-pip .dev
python3.11 -I .installer/pip --isolated --python .dev/bin/python install --require-hashes -r requirements-test.lock
.dev/bin/python -m pytest
.dev/bin/python -m build --no-isolation
.dev/bin/python tools/verify_release.py
```

The artifact verifier inspects exact members, installs the wheel and a wheel built from the extracted source archive into separate environments, and exercises the installed command from both. Tests create disposable repositories only. Do not interpret source tests as proof of deployed integration or public availability.
