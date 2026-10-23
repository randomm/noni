# Publishing noni as a public repository

This is a **checklist for the operator**, not an automation: publishing is
performed manually, and by design this document is checked in so the
checklist survives. The publish is a **fresh repository** — a single clean
initial commit on a new remote — rather than a rewrite of this repository's
history. History violations are **reported** (below) and never rewritten here.

## Before publishing

1. **Verify this tree is clean.** Run the scrub check with the **full local
   deny-list** in place (the untracked `.noni-scrub-denylist` file, or
   `$NONI_SCRUB_DENYLIST` pointing at it):

   ```sh
   uv run pytest tests/test_public_safety.py -q
   ```

   It must pass with no violations. The deny-list file itself is git-ignored
   and is never committed; when it is absent the check skips the deny-list
   class with a prominent stderr notice. **A green run without the deny-list
   is NOT a scrub-clean guarantee** — operator names, external project/tool
   names, and hostnames are only checked by the deny-list class. Before
   publishing, verify the deny-list is present and non-empty (the test output
   must not show the "deny-list class SKIPPED" notice). For a standalone
   operator check, run the CLI directly:

   ```sh
   python scripts/public_safety.py
   ```

   The CLI exits with status 2 (not 0) when the deny-list class was skipped,
   so it will not report a false "clean".
2. **Neutral identity.** Configure a neutral git identity for the new repo
   (e.g. a project name + a project-local email); do not reuse a personal
   identity, hostname or employer address.
3. **Fresh repo.** Create a brand-new remote repository (name it what the
   public project will be called), then make a **single commit** of the
   current tracked tree (the post-#8 tree) as its initial commit:

   ```sh
   git remote add <neutral-remote> <url>
   # create the new repo's branch from this tree's state, then push one commit
   ```

   The tree at this point must already be scrub-clean (the scrub check from
   step 1); the new repo's single commit carries no history, so no history
   violations are carried forward. The neutral identity from step 2 must
   author that commit — every identity in this repo's history is a violation
   listed below, so none of them may be reused.
4. **Recreate open issues.** Recreate each open GitHub issue in the new
   repository with a **scrubbed body**: run the body through the same
   built-in patterns and the local deny-list (the manual audit below names
   every body known to contain a violation), then file the cleaned text as a
   fresh issue. Do not copy issue bodies verbatim.
5. **Recreate the labels and epic map** (`epic` label, E1–E5 → issues #1–#5)
   so the product document's epic map keeps working.

## History-only violation audit (input to the fresh-repo publish)

This repo's history **cannot** be scrubbed here (a rewrite would destroy the
single-clean-commit strategy), so the following is the audit list the
fresh-repo publish must absorb by **not carrying it forward**. Nothing in this
section is a defect in the current tree; every item below lives only in
commit metadata or GitHub issue/PR bodies.

### Commit author identities (git history, all 6 commits)

Identities are referenced **generically on purpose**: quoting them here would
re-introduce exactly the PII this rule removes, so the values live only in
this repo's untracked deny-list (which is itself the audit input) — never in
this document.

- **The operator's personal identity** (personal name + personal email) —
  author of commits `86c3539`, `a2c35d9`, `a3a2428`, `f7787a3`, `6c03672`
  (and of the hygiene commit of this PR, so this list grows by at least one
  authorship at merge). The fresh repo's single commit uses a neutral
  identity instead.
- **A separate agent identity** (agent name + host-local email) — author of
  commit `a48dd46`. Likewise replaced by the neutral identity.

### Commit messages containing paths or names

- `a48dd46` "Split: noni is now the product-direction repo ... moved out with
  full history to <an-external-repo>." — names an external repository.
- `a2c35d9` "Merge pull request #6 from <an-external-repo>/chore/agents-md" —
  names an external repository in the branch name.

### GitHub issue / PR bodies (manual audit; recreate scrubbed)

- **Issue #8 (this ticket)** — its body names external tools/repos and
  machine-local paths in the investigation sections; scrub when recreating.
- Issues #1–#5 (the epic set) and any issue/PR that references the operator's
  other repositories or the paths above. When recreating, scrub each body
  with the same built-in patterns + local deny-list, and file the cleaned
  text as a fresh issue in the new repository.

## After publishing

- Confirm the new repo's initial commit is the only commit (no history).
- Confirm the new repo passes the scrub check with the full deny-list.
- Point any integrations (e.g. the `integrations/` adapters) at the new
  repository.
- This repository becomes private/archival (or is deleted); the public
  project lives in the fresh repository.
