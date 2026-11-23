# Pull request guide for AI coding agents

Give this file to your coding agent before it starts. Each rule links to its
source in [CONTRIBUTING.md](CONTRIBUTING.md) or [CLAUDE.md](../CLAUDE.md).

1. **Start from the latest `main`.** Fetch `main` from
   the upstream repository (`https://github.com/Sarfia-786/adv-eleven-labs.git`; in a
   fork `origin` may be stale), branch from it, and merge it again right before
   you push.
2. **One focused change.** One fix or feature per pull request; no giant or
   mixed pull requests. ([Pull Requests](CONTRIBUTING.md#pull-requests))
3. **Fix the root cause.** Fix the whole class of the bug, not one symptom, and
   add a regression test that fails before the fix and passes after it.
   ([Fix quality](../CLAUDE.md#conventions))
4. **Run the guard tests locally** before you push:
   ```bash
   bun install --frozen-lockfile
   uv run pytest tests/ -q -n auto
   uv run pytest backend/tests/ -q
   bun run check:electron
   bun run --cwd electron locale:check
   ```
   ([Testing](CONTRIBUTING.md#testing))
5. **No formatter churn.** Don't run a formatter over files; change only the
   lines you need, in the file's existing style. ([Code Style](CONTRIBUTING.md#code-style))
6. **UI strings go through i18n,** with the key in every locale file, translated.
   No hardcoded non-English text. ([Quality gates](CONTRIBUTING.md#quality-gates-your-pr-must-pass))
7. **Update the docs in the same pull request** when behaviour they describe
   changes. ([Docs-sync](../CLAUDE.md#conventions))
8. **Add a changelog fragment** for user-visible changes:
   `changelog.d/<PR#>.<type>.md`, one line ending with `(#<PR#>)`. Don't edit
   `CHANGELOG.md`. ([changelog.d](../changelog.d/README.md))
9. **Commit under the contributor's own identity only.** No AI
    `Co-authored-by:` trailers, no "Generated with" lines, no agent session
    links, in commits or the pull request description.
    ([Contributing with AI agents](CONTRIBUTING.md#contributing-with-ai-agents))
10. **Nothing leaves the user's machine without consent.** Add no new network
    calls; the app must work offline with every prompt declined.
    ([Local-first](CONTRIBUTING.md#quality-gates-your-pr-must-pass))
11. **Every new feature needs a tested fallback** to the working path, used
    automatically, with the reason logged.
12. **Never commit secrets,** tokens, local paths or machine details.
13. **Resolve the review bots before asking for review.** Read every
    CodeRabbit and Greptile comment; fix real findings and reply to the rest.
    ([What code review looks like](CONTRIBUTING.md#what-code-review-looks-like))
