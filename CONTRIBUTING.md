# Contributing to Ticket Terminal

Issues and PRs are welcome. Open an issue first for anything you're about to spend real time
on, so it isn't duplicated or built against a direction that's about to change. Otherwise,
just send the PR.

## License

Ticket Terminal is licensed under [Apache 2.0](LICENSE). By contributing, you agree your
contribution is licensed under the same terms (Apache 2.0, section 5). There is no CLA and no
copyright assignment: you keep the copyright in your work.

## Developer Certificate of Origin (DCO)

We use the [DCO](https://developercertificate.org/) instead of a CLA. It is a lightweight
statement that you wrote the change, or otherwise have the right to submit it under the
project's license.

Sign off every commit by adding a `Signed-off-by` line, using the `-s` flag:

```bash
git commit -s -m "Add a thing"
```

This appends:

```
Signed-off-by: Your Name <you@example.com>
```

The name and email must match your commit author. A GitHub Action checks every commit in a
pull request and fails if one is missing a sign-off.

### Sign off automatically

Run this once per clone and every commit gets the sign-off for you (it uses your
`git config user.name` and `user.email`, so set those first):

```bash
scripts/install-hooks.sh
```

### Forgot to sign off?

Last commit only:

```bash
git commit --amend -s --no-edit
git push --force-with-lease
```

Several commits on your branch:

```bash
git rebase --signoff origin/main
git push --force-with-lease
```

## Checks on every pull request

CI runs the backend tests, the UI tests, a full-history secret scan (gitleaks) and the DCO
check. All must pass before merging. Please never commit credentials, tokens or account
identifiers, including in test fixtures.

## Running the tests

```bash
.venv/bin/python -m unittest discover -s tests
npm --prefix tests/ui ci
npm --prefix tests/ui test
```
