#!/bin/sh
# One-time setup: point git at the hooks in scripts/hooks (auto sign-off for the DCO check).
set -e
cd "$(git rev-parse --show-toplevel)"
chmod +x scripts/hooks/*
git config core.hooksPath scripts/hooks

if [ -z "$(git config user.name)" ] || [ -z "$(git config user.email)" ]; then
  echo "Hooks installed, but git user.name / user.email are not set."
  echo "Set them for this repo before committing:"
  echo "  git config user.name  \"Your Name\""
  echo "  git config user.email \"you@example.com\""
else
  echo "Hooks installed. Commits will be signed off as: $(git config user.name) <$(git config user.email)>"
fi
