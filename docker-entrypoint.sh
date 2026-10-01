#!/bin/sh
# /app/data is normally a bind mount (so it survives container restarts — see
# the README's Docker section), which hides whatever the image itself put
# there. The *.example.json files baked into the image at build time live at
# /app/data-examples instead for exactly that reason; reseed them into the
# mounted (possibly empty, on a first run) /app/data here, at container start,
# never clobbering a real file a previous run already wrote.
set -e
mkdir -p /app/data
cp -n /app/data-examples/*.json /app/data/ 2>/dev/null || true
exec "$@"
