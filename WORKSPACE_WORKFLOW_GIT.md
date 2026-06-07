## Git Workflow (MANDATORY)

**Rule:** All merges into `main` must happen **exclusively on GitHub through
a Pull Request**. Do not merge locally into `main`.

- Work must happen on a dedicated branch (`phaseX/y-issue`).
- Integration into `main` happens through a PR merged on GitHub.
- Local `main` is only used for `git pull --ff-only` after the GitHub merge.
- Before opening a PR: run `git fetch origin && git rebase origin/main`
  **from the feature branch** to synchronize it.

**Why:** a local merge into `main` while a PR is still evolving on GitHub
creates divergence and corrupts the shared history.

### Commands Forbidden by Default

- `git merge` (or any equivalent operation) on local `main`, except
  `git pull --ff-only` after the GitHub merge.
- `git push --force` (or `--force-with-lease`) to `main`.
- `git commit` directly on local `main`.

### Nominal Cycle

```bash
# 0. Start work on the issue: assign yourself and move the Project status to
#    "In Progress"
gh issue edit <N> --add-assignee "@me"
# Then update the GitHub Projects "Status" field through the GitHub API.
# Forbidden: gh issue edit <N> --add-label "status:in-progress"

# 1. Start from a clean main
git checkout main && git pull --ff-only

# 2. Create the feature branch
git checkout -b phaseX/y-issue-slug

# 3. Work and make atomic commits
git add ... && git commit -m "..."

# 4. Before the PR: rebase onto the up-to-date main
git fetch origin && git rebase origin/main

# 5. Push and open the PR with gh
git push -u origin phaseX/y-issue-slug
gh pr create --base main --title "..." --body "..."
# MANDATORY: the body MUST contain a "Closes #<N>" line at the top
# (see the "PR-Issue Link" section below).

# 6. After the GitHub merge: clean up locally
git checkout main && git pull --ff-only
git branch -d phaseX/y-issue-slug
```

### PR-Issue Link (MANDATORY)

**Rule:** any PR that resolves an issue MUST contain a GitHub closing keyword
(`Closes`, `Fixes`, `Resolves`) followed by the issue number, **in the PR
body**, ideally on the first line.

```text
Closes #<N>
```

**Why:**

- Only a keyword in the **body** of a PR (or in a commit message merged into
  the default branch) triggers automatic issue closing on GitHub. A
  `Closes #N` in the PR **title** is not enough, because GitHub does not parse
  closing keywords there.
- This populates the issue API field `closedByPullRequestsReferences`, which
  propagates the link to the "Development" views of other issues,
  notifications, and release-notes tooling.
- This avoids forgetting to close the issue manually after the merge.

**GitHub accepted keywords** (case-insensitive): `close`, `closes`, `closed`,
`fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`. Prefer
`Closes #<N>` for consistency.

**For a PR that references an issue without closing it** (dependency, context,
partial work): use `Refs #<N>` or `Related to #<N>`, which create a soft link
without automatic closing.

**Post-creation verification:**

```bash
gh issue view <N> --json closedByPullRequestsReferences
# The field must contain the created PR. If it is empty, the keyword is
# missing or malformed. Fix it with `gh pr edit <PR#> --body "..."`.
```

## GitHub Issues Workflow (MANDATORY)

**Rule:** each issue follows an explicit lifecycle on GitHub, and conversations
must stay in the **right channel** between the issue and its PR to keep both
histories readable.

### When Starting Work on an Issue

1. **Assign yourself the issue** with the configured `gh` account:

   ```bash
   gh issue edit <N> --add-assignee "@me"
   ```

2. **Move the Project status to In Progress through the GitHub API:**

   - Never use a `status:in-progress` label to represent progress status. A
     label is not the issue status.
   - Update the GitHub Projects `Status` field of the item linked to the issue
     and set it to the `In Progress` option.
   - Use the GitHub Projects v2 API, for example through `gh api graphql`,
     after resolving `PROJECT_ID`, `PROJECT_ITEM_ID`, `STATUS_FIELD_ID`, and
     `IN_PROGRESS_OPTION_ID` for the relevant project.

   ```bash
   gh api graphql -f query='
   mutation(
     $projectId: ID!
     $itemId: ID!
     $statusFieldId: ID!
     $inProgressOptionId: String!
   ) {
     updateProjectV2ItemFieldValue(input: {
       projectId: $projectId
       itemId: $itemId
       fieldId: $statusFieldId
       value: { singleSelectOptionId: $inProgressOptionId }
     }) {
       projectV2Item { id }
     }
   }' \
     -F projectId="$PROJECT_ID" \
     -F itemId="$PROJECT_ITEM_ID" \
     -F statusFieldId="$STATUS_FIELD_ID" \
     -F inProgressOptionId="$IN_PROGRESS_OPTION_ID"
   ```

   If the issue is not yet present in the project, first add it through the
   GitHub Projects v2 API (`addProjectV2ItemById`), then apply the status
   mutation above.

### During Implementation (Before Opening the PR)

All conversations related to the **solution design** remain in the issue. Post
there:

- the technical decisions made and their rationale;
- the implementation trade-offs that were arbitrated;
- the clarifications requested and the answers received;
- the divergences identified against the initial plan.

```bash
gh issue comment <N> --body "..."
```

### After Opening the PR

As soon as a PR is opened to resolve the issue, **code review discussions**
move to the PR. The issue stops being the discussion channel:

- reviewer comments (findings, change requests, refactoring suggestions) go
  **in the PR**, not in the issue;
- implementer replies (applied fixes, rationales, counter-arguments to a
  comment) also go **in the PR**, not in the issue;
- the issue receives only high-level summary updates when necessary (major
  blocker, scope change).

```bash
# General comment in the PR
gh pr comment <PR#> --body "..."

# Formal review (approve / request-changes / comment)
gh pr review <PR#> --comment --body "..."
```

### PR Verification / Review (MANDATORY)

When the user asks to **verify**, **reread**, **review**, **check**, or
**validate** a GitHub PR, treat the request as a PR review, not as a simple
local analysis.

**Rule:** every review conclusion must be published on GitHub in the PR before
the final response, unless the user explicitly instructs otherwise (`local
only`, `do not post`, draft, etc.).

Mandatory checklist before responding:

1. Inspect the PR (`gh pr view`, `gh pr diff`, CI checks, linked issue when
   applicable) and run the relevant local tests.
2. Write findings with severity, files/lines, impact, and the expected fix.
3. Publish the review in the PR:
   - blocking finding: prefer `gh pr review <PR#> --request-changes --body
     "..."`;
   - non-blocking findings or informational review: `gh pr review <PR#>
     --comment --body "..."`;
   - no finding: post at least a comment/review stating the checks performed
     and the residual risk.
4. If GitHub refuses the formal review (for example, the configured `gh`
   account is the PR author and cannot request changes), immediately fall back
   to `gh pr comment <PR#> --body "..."` with the same content.
5. The final response must include the link to the published GitHub
   comment/review, the checks that were run, and any limitations.

**Guardrail:** a chat-only response after a PR review request is incomplete.
Never finish the task without a GitHub trace, unless the user explicitly asks
not to post.

**Why:** an issue captures the *problem* and the chosen direction; a PR captures
the *execution* and code review. Mixing the two dilutes both histories and
makes later review harder (audit, post-mortem, new contributor onboarding).
