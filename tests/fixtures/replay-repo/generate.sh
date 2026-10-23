#!/usr/bin/env bash
# Generate a snapshot git repo whose noni/decisions/ tree is a self-contained,
# replayable ledger. The repo is written to the directory given as $1 (default
# .). It carries three records: two in a supersede chain (r1 -> r2, both
# superseded by r3 which is the live record) and one detached record (r4) on a
# different scope. The commit dates are planted so that r2 and r3 have dates
# *reversed* relative to the supersede order — r3 (the superseder) has an
# earlier date than r2 (the superseded) — to pin the rule that supersede-chain
# order is primary and date is only a tie-break.
#
# The repo is a full clone (not shallow), so a fresh clone can replay every
# recorded decision with no shared runtime and no network.
#
#   generate.sh [OUTPUT_DIR]
#
# Requires: git, jq (for the record bodies — they are static JSON, but the
# generator validates them before committing so a malformed fixture never
# reaches the replay test).

set -eu

OUT="${1:-.}"
if [ ! -d "$OUT" ]; then
  mkdir -p "$OUT"
fi
REPO="$OUT/replay-repo"
rm -rf "$REPO"
mkdir -p "$REPO"
cd "$REPO"
git init -q
git config user.name "Replay Fixture"
git config user.email "replay@fixture.invalid"
git config commit.gpgsign false

mkdir -p noni/decisions

# Record r1: root of the chain, superseded. Date: 2026-10-01.
cat > noni/decisions/2026-10-01-r1.json <<'EOF'
{
  "id": "2026-10-01-r1",
  "date": "2026-10-01T10:00:00Z",
  "asked_by": "developer",
  "questions": [
    { "id": "q1", "text": "Adopt the new scheduler?", "options": ["yes", "no", "later"], "answer": "yes" }
  ],
  "by": "Operator",
  "scope": "release ordering",
  "status": "superseded",
  "supersedes": null
}
EOF
git add noni/decisions/2026-10-01-r1.json
GIT_AUTHOR_DATE="2026-10-01T10:00:00Z" GIT_COMMITTER_DATE="2026-10-01T10:00:00Z" \
  git commit -q -m "steering: r1 — adopt the new scheduler"

# Record r2: supersedes r1, itself superseded by r3. Date: 2026-10-22 (LATER than r3).
cat > noni/decisions/2026-10-22-r2.json <<'EOF'
{
  "id": "2026-10-22-r2",
  "date": "2026-10-22T14:03:00Z",
  "asked_by": "developer",
  "questions": [
    { "id": "q1", "text": "Which release carries the new scheduler?", "options": ["next train", "after that", "drop it"], "answer": "next train" }
  ],
  "by": "Operator",
  "scope": "release ordering",
  "status": "superseded",
  "supersedes": "2026-10-01-r1"
}
EOF
git add noni/decisions/2026-10-22-r2.json
GIT_AUTHOR_DATE="2026-10-22T14:03:00Z" GIT_COMMITTER_DATE="2026-10-22T14:03:00Z" \
  git commit -q -m "steering: r2 — scheduler in the next train (supersedes r1)"

# Record r3: supersedes r2, the live record. Date: 2026-10-10 (EARLIER than r2,
# to pin that supersede-chain order beats date in replay ordering).
cat > noni/decisions/2026-10-10-r3.json <<'EOF'
{
  "id": "2026-10-10-r3",
  "date": "2026-10-10T09:00:00Z",
  "asked_by": "developer",
  "questions": [
    { "id": "q1", "text": "Which release carries the new scheduler?", "options": ["next train", "after that", "drop it"], "answer": "after that" }
  ],
  "by": "Operator",
  "scope": "release ordering",
  "status": "decided",
  "supersedes": "2026-10-22-r2"
}
EOF
git add noni/decisions/2026-10-10-r3.json
GIT_AUTHOR_DATE="2026-10-10T09:00:00Z" GIT_COMMITTER_DATE="2026-10-10T09:00:00Z" \
  git commit -q -m "steering: r3 — scheduler in the train after that (supersedes r2)"

# Record r4: detached root, different scope, no supersede relationship to r1-r3.
cat > noni/decisions/2026-10-25-r4.json <<'EOF'
{
  "id": "2026-10-25-r4",
  "date": "2026-10-25T11:00:00Z",
  "asked_by": "developer",
  "questions": [
    { "id": "q1", "text": "Adopt the new linter?", "options": ["yes", "no", "later"], "answer": "yes" }
  ],
  "by": "Operator",
  "scope": "tooling",
  "status": "decided",
  "supersedes": null
}
EOF
git add noni/decisions/2026-10-25-r4.json
GIT_AUTHOR_DATE="2026-10-25T11:00:00Z" GIT_COMMITTER_DATE="2026-10-25T11:00:00Z" \
  git commit -q -m "steering: r4 — adopt the new linter (detached)"

echo "Generated replay repo at $REPO"
echo "Records:"
git log --oneline
echo "Ledger:"
ls -1 noni/decisions/
