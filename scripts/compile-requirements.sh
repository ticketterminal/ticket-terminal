#!/bin/sh
# Regenerates the hash-pinned requirements.txt from requirements.in.
# Run this after editing requirements.in (adding/bumping a direct dependency).
#
# --universal: this project installs on macOS (native dev), Linux (Docker,
# CI) and whatever each contributor runs locally, so the lockfile needs
# hashes for all of them, not just whichever platform happens to run this
# script.
set -e
cd "$(git rev-parse --show-toplevel)"
uv pip compile --universal --generate-hashes -o requirements.txt requirements.in
