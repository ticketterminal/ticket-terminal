const CAMPAIGNS = {
  "/go/reddit-agents": {
    content: "agent_tools",
    destination:
      "https://github.com/ticketterminal/ticket-terminal?utm_source=reddit&utm_medium=paid_social&utm_campaign=canonical_demo_nov_2026&utm_content=agent_tools#clone-and-run-locally",
  },
  "/go/reddit-jira": {
    content: "jira_continuity",
    destination:
      "https://github.com/ticketterminal/ticket-terminal?utm_source=reddit&utm_medium=paid_social&utm_campaign=canonical_demo_nov_2026&utm_content=jira_continuity#clone-and-run-locally",
  },
};

const VISITOR_COOKIE = "tt_anon";
const CAMPAIGN_NAME = "canonical_demo_nov_2026";

function normalizePath(pathname) {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

function cookieValue(cookieHeader, name) {
  for (const pair of (cookieHeader || "").split(";")) {
    const [key, ...value] = pair.trim().split("=");
    if (key === name) return value.join("=");
  }
  return null;
}

function referrerHost(value) {
  if (!value) return "direct";
  try {
    return new URL(value).hostname || "direct";
  } catch {
    return "invalid";
  }
}

function isAutomatedRequest(request) {
  if (request.method !== "GET") return true;
  const userAgent = request.headers.get("user-agent") || "";
  return /bot|crawler|spider|preview|facebookexternalhit|slackbot|discordbot/i.test(
    userAgent,
  );
}

function redirectWithTracking(request, env, campaign) {
  const requestUrl = new URL(request.url);
  const existingVisitor = cookieValue(request.headers.get("cookie"), VISITOR_COOKIE);
  const visitorId = existingVisitor || crypto.randomUUID();

  if (!isAutomatedRequest(request)) {
    env.CAMPAIGN_CLICKS.writeDataPoint({
      indexes: [requestUrl.hostname],
      blobs: [
        CAMPAIGN_NAME,
        campaign.content,
        request.cf?.country || "unknown",
        referrerHost(request.headers.get("referer")),
        visitorId,
      ],
      doubles: [1],
    });
  }

  const headers = new Headers({
    Location: campaign.destination,
    "Cache-Control": "no-store, private",
    "Referrer-Policy": "strict-origin-when-cross-origin",
  });

  if (!existingVisitor) {
    headers.append(
      "Set-Cookie",
      `${VISITOR_COOKIE}=${visitorId}; Max-Age=2592000; Path=/go/; Secure; HttpOnly; SameSite=Lax`,
    );
  }

  return new Response(null, { status: 302, headers });
}

function authorizedForStats(request, env) {
  const authorization = request.headers.get("authorization") || "";
  return Boolean(
    env.CAMPAIGN_STATS_TOKEN &&
      authorization === `Bearer ${env.CAMPAIGN_STATS_TOKEN}`,
  );
}

async function campaignStats(request, env) {
  if (!authorizedForStats(request, env)) {
    return Response.json(
      { error: "Unauthorized" },
      { status: 401, headers: { "Cache-Control": "no-store, private" } },
    );
  }

  try {
    const result = await env.ANALYTICS_SQL.query({
      query: `
        SELECT
          blob2 AS content,
          COUNT(*) AS clicks,
          COUNT(DISTINCT blob5) AS unique_visitors
        FROM events.analyticsEngine."ticket_terminal_campaign_clicks"
        WHERE timestamp >= NOW() - INTERVAL '30' DAY
          AND blob1 = $campaign
        GROUP BY content
        ORDER BY clicks DESC
      `,
      params: { campaign: CAMPAIGN_NAME },
    });

    return Response.json(
      {
        campaign: CAMPAIGN_NAME,
        window_days: 30,
        routes: result.data || [],
        privacy:
          "Aggregate first-party counts only. No names, emails, IP addresses, or fingerprinting are stored.",
      },
      { headers: { "Cache-Control": "no-store, private" } },
    );
  } catch (error) {
    return Response.json(
      {
        campaign: CAMPAIGN_NAME,
        window_days: 30,
        routes: [],
        pending: true,
        message: "Analytics are initializing. Check again after the first campaign click.",
      },
      { status: 202, headers: { "Cache-Control": "no-store, private" } },
    );
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = normalizePath(url.pathname);
    const campaign = CAMPAIGNS[path];

    if (campaign && (request.method === "GET" || request.method === "HEAD")) {
      return redirectWithTracking(request, env, campaign);
    }

    if (path === "/api/campaign-stats" && request.method === "GET") {
      return campaignStats(request, env);
    }

    return env.ASSETS.fetch(request);
  },
};
