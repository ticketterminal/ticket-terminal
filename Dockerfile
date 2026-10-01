# Packages the Ticket Terminal server itself (Python + Node, for codeburn's cost
# badges) plus both agent CLIs. It does NOT sandbox agent sessions — `workDir`,
# git credentials, cloud SSO caches and kubeconfig are all expected to reach the
# container via the same $HOME bind mount documented in the README, so a session
# started here can still run real commands against your real repos. See the
# README's "Docker" section before building or running this.
FROM python:3.12-slim-bookworm
ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates xz-utils git openssh-client ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Node, straight from nodejs.org's own distribution (no third-party apt repo) —
# needed only so `npm install -g` below has something to run its postinstall
# with. Bump NODE_VERSION periodically; the installed claude/codex binaries
# below are native and do not need Node at runtime themselves.
ENV NODE_VERSION=22.23.3
RUN NODE_ARCH=$([ "$TARGETARCH" = "arm64" ] && echo arm64 || echo x64) \
    && curl -fsSL -o /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz

# Both agent CLIs, via their own official installers — see the README's Docker
# section for why these are baked into the image while auth/config (~/.claude,
# ~/.codex) comes from the bind-mounted host $HOME instead.
RUN npm install -g @anthropic-ai/claude-code codeburn \
    && CODEX_NON_INTERACTIVE=true sh -c "curl -fsSL https://chatgpt.com/codex/install.sh | sh" \
    && mv /root/.local/bin/codex /usr/local/bin/codex \
    && rm -rf /root/.npm /root/.cache /root/.local

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY server/ server/
COPY public/ public/
COPY data/*.example.json data/
COPY MEMORY_FORMAT.md .

EXPOSE 4173
CMD ["python", "server/main.py"]
