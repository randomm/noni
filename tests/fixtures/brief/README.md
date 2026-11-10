Fixtures for `noni brief`: the state root the tool reads, and the builder that plants it.

`generate.py` is the one place the fixture's content is spelled. `brief.tar`, committed
beside it, is the repository that script produces: a git repository holding the state root
the brief reads -- eleven order entries over one `confirmed` instant, one standing intent
whose `## Purpose` body runs past the brief's 20-line clip, and one decided record that
every order entry and the intent's own commit cite. `tests/test_brief_fixture.py` regenerates the tar into a
throwaway directory and compares it member by member, so the committed bytes cannot drift
from the script while the suite still passes.

The tree travels as a tar and not as a directory because a repository's own `index` is
binary and the purity suites read every file under `tests/fixtures/` as UTF-8. `tests/
brief_fixtures.py` unpacks it into a case's `tmp_path` and renames `.git` to `.git-brief`,
which hides the copy from any outer repository; a case that wants the census to read the
history puts the name back for the length of the run.

Run the builder to see the tree without unpacking anything:

```
python tests/fixtures/brief/generate.py            # describe it
python tests/fixtures/brief/generate.py OUT.tar    # write it
```
