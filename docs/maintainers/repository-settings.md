# Repository settings

GitHub stores these settings outside the repository, so no file or CI check can
enforce them. Apply them once as a repository admin, then re-check them after
changing workflow or job names. The `gh api` commands below assume an
authenticated `gh` with admin access to the repository named in the command.

## Ruleset: `main`

The example ruleset requires a pull request, the aggregate CI result and the
commit identity checks. It also prevents branch deletion and force pushes.

GitHub attaches commit statuses to a SHA. The identity check requires each open
pull request to have a unique head and checks again before publishing a result.
After closing a duplicate, rerun the surviving pull request’s identity workflow.

These checks are asynchronous, not an atomic lock on GitHub metadata at merge
time. Wait for the newest head and metadata checks after edits, including
closing duplicates. A metadata change detected during evaluation leaves the
status pending and fails the native job; rerun that target workflow. Initial
rollout is deliberately manual: land the trusted workflows before making their
contexts required. Repository writers who can publish commit statuses remain
inside the administrative trust boundary.

The `context` values must match the check names shown on a pull request:

- `Tests (backend + frontend)`: the `name:` of the `test` job in `.github/workflows/ci.yml`. It is a gate that waits for the `test-python` and `test-electron` jobs, so keep this name when changing either.
- `Commit identities`: the native job in `.github/workflows/commit-identity.yml`.
  It runs only base-owned code through `pull_request_target` and fails on API,
  fetch, or policy-execution errors. PR commits are fetched as git objects;
  PR files are never checked out and there is no PR-owned bootstrap fallback.
- `Commit identity policy`: the privileged commit status written by
  `.github/scripts/identity_check.py`. An unprivileged fork workflow can copy
  a native job name, but cannot overwrite this status with its read-only token.
  Require both the native job and this status. The policy reads current PR
  metadata and checks the head/base/description again before publishing. A
  stale event cannot approve a newer head, and the policy checkout must match
  the current base SHA; synchronize the PR with `main` to obtain a fresh run.
GitHub evaluates native jobs triggered by `pull_request_target` as required
checks; `issue_comment` jobs are not eligible. See [GitHub's required-check
troubleshooting guide](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks#checks-from-some-workflow-jobs-are-not-evaluated).

`integration_id` 15368 is GitHub Actions, so only workflow runs can satisfy the
native checks. The `Commit identity policy` entry omits it so the status can be published by the trusted identity workflow. `strict_required_status_checks_policy` requires branches to be up
to date with `main` before merging.

```bash
gh api --method POST 'repos/{owner}/{repo}/rulesets' --input - <<'JSON'
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request" }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "Tests (backend + frontend)", "integration_id": 15368 },
          { "context": "Commit identities", "integration_id": 15368 },
          { "context": "Commit identity policy" }
        ]
      }
    }
  ]
}
JSON
```

The bypass lets repository admins merge a pull request whose checks are not
green, for example to land an urgent fix, but never to push to `main` directly.
Remove the bypass entry for a stricter
setup. Do not enable "Require review from
Code Owners" while `@debpalash` is the only code owner, because GitHub does not
let authors approve their own pull requests.

UI: **Settings → Rules → Rulesets → New ruleset → New branch ruleset**. Set the
target to the default branch, enable **Restrict deletions**, **Require a pull
request before merging** (required approvals: 0, all other options off),
**Block force pushes** and **Require status checks to pass**, then add
`Tests (backend + frontend)` and `Commit identities` with source
**GitHub Actions**, plus the `Commit identity policy` status.

## Secret scanning and push protection

UI: **Settings → Code security → Secret Protection**. Enable **Secret scanning**
and **Push protection**.

```bash
gh api --method PATCH repos/debpalash/VoiceStudio --input - <<'JSON'
{ "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" } } }
JSON
```

The Supermetry site id in `config/analytics.json` is public by design and is not
a credential (see `tests/test_no_committed_analytics_token.py`, which bans any
dashboard or API key). If an alert flags it, close it as "false positive".

## Private vulnerability reporting

`.github/SECURITY.md` names GitHub Security Advisories as the preferred channel,
and that link only works while this setting is on.

UI: **Settings → Code security → Private vulnerability reporting → Enable**.

```bash
gh api --method PUT repos/debpalash/VoiceStudio/private-vulnerability-reporting
```

## Dependabot alerts

UI: **Settings → Code security → Dependabot alerts → Enable**. This setting
turns on security alerts. Version updates for GitHub Actions are configured
separately in `.github/dependabot.yml`.

```bash
gh api --method PUT repos/debpalash/VoiceStudio/vulnerability-alerts
```

## Maintainer commit email

Each maintainer should go to **GitHub → Settings → Emails** and enable **Keep my
email addresses private** and **Block command line pushes that expose my
email**. Then set the no-reply address shown on that page as the commit
identity:

```bash
git config --global user.email "ID+USERNAME@users.noreply.github.com"
```

Commits keep their GitHub attribution, and `scripts/cla_audit.py` maps no-reply
addresses to GitHub logins without an API lookup. Commits already pushed
keep their old address.

The contributor audit inventories text blobs in `HEAD`, independent of staged
changes. Submodule gitlinks are excluded: their repositories require separate
licence and contributor audits. A failed blame of an included file stops the
audit rather than understating unsigned contributions.
