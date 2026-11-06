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
   names, and hostnames are only checked by the deny-list class. The pytest
   run above is not by itself proof the deny-list was active (a run with the
   deny-list absent or empty also passes); the authoritative pre-publish
   check is the CLI directly:

   ```sh
   python scripts/public_safety.py
   ```

   The CLI exits with status 2 (not 0) when the deny-list class was not
   active — absent, unreadable, or present-but-empty (zero usable entries) —
   so it will not report a false "clean" in any of those states. It exits 3
   when the gate could not run at all (the ``noni`` package was not
   importable), which is a different state from 2: 2 is a scan that ran with
   half its vocabulary missing, 3 is a scan that never started.

   `scripts/public_safety.py` is a wrapper: the checks it runs live in
   `src/noni/public_safety.py`, and the wrapper adds only the tree to audit
   (this repository's root) and the exit-code contract above. Scrubbing the
   package and scrubbing the wrapper are the same check over the same tree;
   `tests/test_wheel_contents.py` is what keeps the built wheel from shipping a
   file this check never saw.
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
5. **Recreate the labels** the open issues carry (``epic`` and any label an
   open issue has), so a recreated issue keeps the label it was worked under.

## History-only violation audit (input to the fresh-repo publish)

This repo's history **cannot** be scrubbed here (a rewrite would destroy the
single-clean-commit strategy), so the following is the audit the fresh-repo
publish must absorb by **not carrying it forward**. Nothing in this section is a
defect in the current tree; every class of item lives only in commit metadata or
GitHub issue/PR bodies. **Generate the list at publish time** rather than
maintaining it here: a hardcoded count or hash list is stale the moment another
commit lands, which is the state this page used to be in.

### Commit author identities

Identities are referenced **generically on purpose**: quoting them here would
re-introduce exactly the PII this rule removes, so the values live only in this
repo's untracked deny-list (which is itself the audit input) — never in this
document.

Enumerate every identity the history carries, and match each against the
deny-list:

```sh
git log --format='%an <%ae> %cn <%ce>' | sort -u
```

Expect at least two classes of offender: the operator's personal identity
(personal name + personal email), and a separate agent identity (agent name +
host-local email). Neither may author the new repository's single commit, which
the neutral identity from step 2 writes instead. Read the list fresh: new
commits add authorships, so any count in this document would already be wrong.

### Commit messages containing paths or names

Enumerate the messages, and match each against the built-in patterns and the
deny-list:

```sh
git log --format='%H %s'
```

Expect commits that name an external repository — a split commit whose body says
history was moved out to another repository, and merge commits that carry a
foreign repository name in the branch. Each is reported here as a class and
never quoted: quoting the subject would reproduce the violation.

### GitHub issue / PR bodies (manual audit; recreate scrubbed)

Enumerate the open issues and pull requests, and audit each body:

```sh
gh issue list --state all --json number,title
```

The bodies known to need scrubbing are the ones carrying investigation
sections — those name external tools and repositories, and machine-local paths —
and any body that references the operator's other repositories or the paths
above. Scrub each with the same built-in patterns + local deny-list, and file
the cleaned text as a fresh issue in the new repository.

## After publishing

- Confirm the new repo's initial commit is the only commit (no history).
- Confirm the new repo passes the scrub check with the full deny-list.
- Point any integrations (e.g. the `integrations/` adapters) at the new
  repository.
- This repository becomes private/archival (or is deleted); the public
  project lives in the fresh repository.
