# The hygiene scan's artifacts

How the `hygiene` class names what it found, for the consumers that read
`--json` rows. The class itself is documented by the census skill
(`skills/census/SKILL.md`), which owns the exit codes; this page owns the
artifact naming, which is a property of the checker rather than of the run.

### The hygiene artifact namespace

`hygiene` rows live in two artifact namespaces, and which one applies is
decided by `subject`, which is therefore the machine-readable discriminator —
consumers should branch on it rather than matching message prose:

| `subject` | meaning | `artifact` |
|---|---|---|
| `path:line` of a tracked file | a built-in or active deny-list violation, or an allowlist finding (stale, refused) at line 0 | that file, root-relative |
| `hygiene scan` | the scan itself did not run (no git tree, `git ls-files` failed or hung, `public_safety` not importable, or the committed allowlist unreadable or refused) | the checker, in the hygiene artifact namespace (`noni/public_safety.py`) |
| `deny-list` | the deny-list half of the scan did not run; the state word (`absent`, `corrupt`, `present but empty`) is in the message | the checker, as above |

A violating file's artifact is rooted in the tree being audited; the two
probe-failure rows name the census's own checker, which ships inside the
package rather than beside the tree, so they are rooted in the hygiene artifact
namespace instead — the census never prints a machine-local absolute path either
way. A tracked path may contain a
colon, so the census splits public_safety's `path:line: label` on its known
label set rather than on the first colon, and a violation of an unexpected
shape is reported verbatim instead of split; an allowlist finding is reported at line 0.
