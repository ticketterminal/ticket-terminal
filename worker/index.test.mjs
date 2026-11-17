import assert from "node:assert/strict";
import test from "node:test";

import worker from "./index.js";

function testEnv() {
  const points = [];
  return {
    points,
    env: {
      CAMPAIGN_CLICKS: {
        writeDataPoint(point) {
          points.push(point);
        },
      },
      ANALYTICS_SQL: {
        async query() {
          return {
            data: [
              { content: "agent_tools", clicks: 3, unique_visitors: 2 },
            ],
          };
        },
      },
      CAMPAIGN_STATS_TOKEN: "test-token",
      ASSETS: {
        async fetch() {
          return new Response("asset");
        },
      },
    },
  };
}

test("tracks the agent campaign and redirects to the attributed GitHub URL", async () => {
  const { env, points } = testEnv();
  const response = await worker.fetch(
    new Request("https://ticketterminal.dev/go/reddit-agents/", {
      headers: { referer: "https://www.reddit.com/r/codex/" },
    }),
    env,
  );

  assert.equal(response.status, 302);
  assert.match(response.headers.get("location"), /utm_content=agent_tools/);
  assert.match(response.headers.get("set-cookie"), /^tt_anon=/);
  assert.equal(points.length, 1);
  assert.equal(points[0].blobs[1], "agent_tools");
  assert.equal(points[0].blobs[3], "www.reddit.com");
});

test("reuses the anonymous first-party visitor cookie", async () => {
  const { env, points } = testEnv();
  const response = await worker.fetch(
    new Request("https://ticketterminal.dev/go/reddit-jira", {
      headers: { cookie: "tt_anon=visitor-123" },
    }),
    env,
  );

  assert.equal(response.status, 302);
  assert.equal(response.headers.get("set-cookie"), null);
  assert.equal(points[0].blobs[1], "jira_continuity");
  assert.equal(points[0].blobs[4], "visitor-123");
});

test("returns aggregate stats without exposing visitor identifiers", async () => {
  const { env } = testEnv();
  const response = await worker.fetch(
    new Request("https://ticketterminal.dev/api/campaign-stats", {
      headers: { authorization: "Bearer test-token" },
    }),
    env,
  );
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.deepEqual(body.routes, [
    { content: "agent_tools", clicks: 3, unique_visitors: 2 },
  ]);
  assert.doesNotMatch(JSON.stringify(body), /visitor-123/);
});

test("keeps campaign statistics private", async () => {
  const { env } = testEnv();
  const response = await worker.fetch(
    new Request("https://ticketterminal.dev/api/campaign-stats"),
    env,
  );

  assert.equal(response.status, 401);
});

test("does not count bot previews or HEAD requests", async () => {
  const { env, points } = testEnv();
  await worker.fetch(
    new Request("https://ticketterminal.dev/go/reddit-agents", {
      headers: { "user-agent": "redditbot/1.0" },
    }),
    env,
  );
  await worker.fetch(
    new Request("https://ticketterminal.dev/go/reddit-agents", {
      method: "HEAD",
    }),
    env,
  );

  assert.equal(points.length, 0);
});

test("passes unrelated requests through to static assets", async () => {
  const { env } = testEnv();
  const response = await worker.fetch(
    new Request("https://ticketterminal.dev/assets/ticket-terminal-demo.mp4"),
    env,
  );

  assert.equal(await response.text(), "asset");
});
