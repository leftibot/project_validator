# The project corpus

Real repositories, each pinned to a commit, validated as they are. The unit tests' fixtures (`tests/fixtures`) are
small and written to be judged; the corpus is the other half of the regression suite: the projects as their authors
wrote them, one or more for every ecosystem profile. Nothing is recorded in the repository: a recording is made when
needed, and two recordings are compared, so every run also exercises every parser over real inputs.

- `projects.toml` lists each project: its GitHub `owner/repo`, the commit it is pinned to, the ecosystems it stands
  for (the labels of the support matrix; a recording must detect each of them), optional notes, and the open upstream
  issues about what the validator gets wrong on it.
- A recording (`python -m corpus record DIR`) holds, per project, the project map (`--map`), the results judged with
  `--allow-unknown` (each check's status, message and details, as `--format json` prints them, without the per-place
  copies) and what strict judging adds: each check's status, and the distinct reasons something could not be read, so
  a parser that learns a construct removes its reason.

Where the audit of a project found the validator wrong, the manifest's `issues` names the issue, and where a small
project reproduces the wrong result, a test in `tests/regressions/` asserts the right behaviour as an expected
failure (`@unittest.expectedFailure  # upstream #N`): the fix makes it an unexpected success, and the decorator goes
with the issue. The fix also shows in the corpus diff of its pull request, on the projects the issue names.

## Running

```sh
python -m corpus record out/head              # fetch (once), validate, write out/head/<owner>--<repo>.json
python -m corpus record out/head fmtlib/fmt   # one project
python -m corpus diff out/base out/head       # what changed: per project, the checks whose status changed
python -m corpus diff out/base out/head --full
python -m corpus fetch                        # fill the cache and stop
```

`record` exits 1 when a project crashes the extraction or an ecosystem it stands for is not detected, unless the
manifest names open issues against the project (then the shortfall is known, reported and not fatal). Checkouts are
fetched shallowly (one commit, no history) into `$PROJECT_VALIDATOR_CORPUS`, else `~/.cache/project_validator/corpus`
(`--cache DIR` overrides both); about 5 GB for the whole corpus. They are git checkouts, not archives: an archive
leaves out what `.gitattributes` export-ignores, often the CI configuration itself. `--jobs N` validates N projects
at once (default 4). `--manifest FILE` reads another manifest, which is how CI runs the base branch's validator over
the pull request's project list.

CI (the `corpus` job) records the pull request's head and, in a worktree, its base, over the same checkouts, and
puts `python -m corpus diff` in the job summary; the head recording is an artifact. The job fails only when the head
recording falls short (a crash, an ecosystem not detected) on a project with no issue to account for it: what changed
is for the review to judge, since a change in what is recognised is meant to show there.

## Adding a project

Pick a repository that uses the ecosystem's usual tooling, pin it to its current default-branch commit
(`git ls-remote https://github.com/owner/repo HEAD`), add it to `projects.toml`, run
`python -m corpus record out/new owner/repo`, and read the recording against the repository: every result the
validator gets wrong is an upstream issue, listed in `issues`. `tests/test_corpus.py` checks the manifest offline.
