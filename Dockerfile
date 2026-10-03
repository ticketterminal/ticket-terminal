# Packages the Ticket Terminal server itself (Python + Node, for codeburn's cost
# badges) plus both agent CLIs. It does NOT sandbox agent sessions — `workDir`,
# git credentials, cloud SSO caches and kubeconfig are all expected to reach the
# container via the same $HOME bind mount documented in the README, so a session
# started here can still run real commands against your real repos. See the
# README's "Docker" section before building or running this.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates xz-utils git openssh-client ripgrep procps \
    && rm -rf /var/lib/apt/lists/*

# Node, straight from nodejs.org's own distribution (no third-party apt repo) —
# needed only so `npm install -g` below has something to run its postinstall
# with. Bump NODE_VERSION periodically; the installed claude/codex binaries
# below are native and do not need Node at runtime themselves.
# `uname -m` (not an ARG like TARGETARCH) so this is correct under the classic
# builder too, not just BuildKit — verified live: the classic builder here
# never populated TARGETARCH, which silently installed the wrong-arch Node.
ENV NODE_VERSION=22.23.3
RUN NODE_ARCH=$([ "$(uname -m)" = "aarch64" ] && echo arm64 || echo x64) \
    && curl -fsSL -o /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz

# Both agent CLIs, via their own official installers — see the README's Docker
# section for why these are baked into the image while auth/config (~/.claude,
# ~/.codex) comes from the bind-mounted host $HOME instead.
#
# DISABLE_UPDATES: this image already pins claude's version at build time (bump it
# by rebuilding), so the npm-installed binary should never try to self-update —
# verified live: npm's global prefix here is only writable by the uid that ran this
# RUN (root), while the container runs as whatever arbitrary host uid owns the
# bind-mounted $HOME (see the codex chmod below for the same constraint), so an
# update attempt just fails with a "no write permission to npm prefix" error on
# every session start instead of silently no-op-ing.
ENV DISABLE_UPDATES=1
RUN npm install -g @anthropic-ai/claude-code codeburn \
    # CODEX_HOME=/opt/codex-home for the INSTALL only, not a persistent ENV —
    # the installer's real payload must land somewhere every --user can reach
    # (verified live: /root is 0700, so chmod-ing just .codex inside it is not
    # enough, and the whole README bind-mount design means this image is run
    # as arbitrary host uids). At container runtime codex must still fall back
    # to $HOME/.codex (the bind-mounted real one) for auth/session continuity,
    # which baking CODEX_HOME in as ENV would have broken. /usr/local/bin/codex
    # ends up a symlink into /opt/codex-home instead of /root/.codex — that is
    # the only thing this changes. /opt is world-traversable by default; the
    # chmod below is just making that explicit rather than trusting it. BIN_DIR
    # is untouched (still $HOME/.local/bin, i.e. /root at build time) since the
    # existing mv below already relocates that symlink regardless.
    && CODEX_NON_INTERACTIVE=true CODEX_HOME=/opt/codex-home sh -c "curl -fsSL https://chatgpt.com/codex/install.sh | sh" \
    && chmod -R a+rX /opt/codex-home \
    && mv /root/.local/bin/codex /usr/local/bin/codex \
    && rm -rf /root/.npm /root/.cache /root/.local

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY server/ server/
COPY public/ public/
# Not data/ directly — a bind mount over /app/data at runtime would hide these.
# See docker-entrypoint.sh, which reseeds them into /app/data at container start.
COPY data/*.example.json data-examples/
COPY MEMORY_FORMAT.md .
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 4173
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "server/main.py"]
