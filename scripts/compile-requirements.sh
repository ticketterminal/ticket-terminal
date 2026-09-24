#!/bin/sh
# Regenerates the hash-pinned requirements.txt from requirements.in.
# Run this after editing requirements.in (adding/bumping a direct dependency).
set -e
cd "$(git rev-parse --show-toplevel)"
python3 -m pip install -q pip-tools
python3 -m piptools compile --generate-hashes -o requirements.txt requirements.in
