/**
 * Cloudflare Worker — recitation (Gradio 6+) + analytics
 *
 * Secrets / vars (wrangler or dashboard — NEVER commit real tokens):
 *   wrangler secret put CF_API_TOKEN
 *   wrangler secret put CF_ZONE_ID
 *   wrangler secret put HF_SPACE_URL   → https://facilitator999-quranforyunus.hf.space
 * Optional:
 *   ALLOWED_ORIGIN → https://www.quranforyunus.com
 *
 * Gradio 6+ uses POST .../gradio_api/call/check_recitation then GET .../call/.../event_id (SSE).
 * Legacy /api/predict returns 404.
 *
 * Identify mode: FormData field mode=identify (still send audio). Uses a neutral dummy
 * expected string so the space returns transcript; client matches surah locally.
 */

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders(env) });
    if (request.method === "POST") return handleRecitation(request, env);
    if (request.method === "GET") return handleAnalytics(request, env);
    return jsonError(env, "Method not allowed", 405);
  },
};

// ─────────────────────────────────────────────────────────────
//  RECITATION — Hugging Face Space (Gradio 6)
// ─────────────────────────────────────────────────────────────
async function handleRecitation(request, env) {
  const HF = (env.HF_SPACE_URL || "").replace(/\/$/, "");
  if (!HF) return jsonError(env, "HF_SPACE_URL not set", 500);

  try {
    const formData = await request.formData();
    const audio = formData.get("audio");
    const mode = formData.get("mode");

    if (!audio) return jsonError(env, "No audio provided", 400);

    let expected;
    if (mode === "identify") {
      // Long neutral Arabic so HF still runs ASR and returns transcript in JSON.
      expected =
        "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَٰلَمِينَ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ مَٰلِكِ يَوْمِ ٱلدِّينِ";
    } else {
      expected = formData.get("expected");
      if (!expected) return jsonError(env, "No expected text provided", 400);
    }

    const base64 = bytesToBase64(new Uint8Array(await audio.arrayBuffer()));

    const callUrl = `${HF}/gradio_api/call/check_recitation`;
    const initRes = await fetch(callUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data: [base64, expected] }),
    });

    if (!initRes.ok) {
      const txt = await initRes.text();
      return jsonError(env, `HF Gradio call failed ${initRes.status}: ${txt}`, 502);
    }

    const { event_id: eventId } = await initRes.json();
    if (!eventId) return jsonError(env, "HF returned no event_id", 502);

    const sseRes = await fetch(`${callUrl}/${eventId}`, { method: "GET" });
    if (!sseRes.ok) {
      const txt = await sseRes.text();
      return jsonError(env, `HF Gradio result failed ${sseRes.status}: ${txt}`, 502);
    }

    const result = parseGradioSse(await sseRes.text());

    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json", ...corsHeaders(env) },
    });
  } catch (e) {
    return jsonError(env, e.message || String(e), 500);
  }
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function parseGradioSse(sseText) {
  const blocks = sseText.split(/\r?\n\r?\n/);
  for (const block of blocks) {
    if (block.includes("event: error")) {
      const line = block.split("\n").find((l) => l.startsWith("data: "));
      if (line) {
        const raw = line.slice(6).trim();
        let msg = raw;
        try {
          const outer = JSON.parse(raw);
          msg = Array.isArray(outer) ? String(outer[0]) : JSON.stringify(outer);
        } catch (_) {
          /* keep raw */
        }
        throw new Error(msg || "Gradio event error");
      }
    }
    if (block.includes("event: complete")) {
      const line = block.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const raw = line.slice(6).trim();
      const outer = JSON.parse(raw);
      if (!Array.isArray(outer) || outer[0] == null) {
        throw new Error("Unexpected Gradio response shape");
      }
      const inner = outer[0];
      return typeof inner === "string" ? JSON.parse(inner) : inner;
    }
  }
  throw new Error("No complete event from Gradio (timeout or empty SSE)");
}

// ─────────────────────────────────────────────────────────────
//  ANALYTICS
// ─────────────────────────────────────────────────────────────
async function handleAnalytics(request, env) {
  const token = env.CF_API_TOKEN;
  const zoneId = env.CF_ZONE_ID;
  if (!token || !zoneId) {
    return jsonError(env, "CF_API_TOKEN or CF_ZONE_ID not set", 500);
  }

  const url = new URL(request.url);
  const days = Math.min(parseInt(url.searchParams.get("days") || "3", 10), 30);
  const since = daysAgo(days);

  const query = `{
    viewer {
      zones(filter: { zoneTag: "${zoneId}" }) {
        httpRequests1dGroups(
          limit: ${days},
          orderBy: [date_DESC],
          filter: { date_geq: "${since}" }
        ) {
          dimensions { date }
          sum {
            pageViews
            requests
            countryMap { clientCountryName requests threats }
          }
        }
      }
    }
  }`;

  try {
    const resp = await fetch("https://api.cloudflare.com/client/v4/graphql", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ query }),
    });

    if (!resp.ok) return jsonError(env, `CF API error: ${resp.status}`, 502);
    const raw = await resp.json();
    if (raw.errors) return jsonError(env, raw.errors[0]?.message || "GraphQL error", 502);

    const groups = raw?.data?.viewer?.zones?.[0]?.httpRequests1dGroups || [];
    const countryTotals = {};
    let totalRequests = 0;
    let totalBots = 0;
    let totalPageViews = 0;

    const daily = groups
      .map((g) => {
        const requests = g.sum?.requests || 0;
        const threats =
          g.sum?.countryMap?.reduce((a, c) => a + (c.threats || 0), 0) || 0;
        totalRequests += requests;
        totalBots += threats;
        totalPageViews += g.sum?.pageViews || 0;

        (g.sum?.countryMap || []).forEach((c) => {
          const name = c.clientCountryName || "Unknown";
          if (!countryTotals[name]) countryTotals[name] = { requests: 0, threats: 0 };
          countryTotals[name].requests += c.requests || 0;
          countryTotals[name].threats += c.threats || 0;
        });

        return {
          date: g.dimensions.date,
          visitors: Math.max(0, requests - threats),
          pageViews: g.sum?.pageViews || 0,
        };
      })
      .reverse();

    const countries = Object.entries(countryTotals)
      .map(([name, d]) => ({
        country: name,
        humanRequests: Math.max(0, d.requests - d.threats),
        botRequests: d.threats,
      }))
      .sort((a, b) => b.humanRequests - a.humanRequests)
      .slice(0, 50);

    return new Response(
      JSON.stringify({
        summary: {
          totalRequests: totalRequests - totalBots,
          totalPageViews,
          totalBotThreats: totalBots,
          days,
          since,
        },
        daily,
        countries,
      }),
      { headers: { "Content-Type": "application/json", ...corsHeaders(env) } }
    );
  } catch (e) {
    return jsonError(env, e.message, 500);
  }
}

// ─────────────────────────────────────────────────────────────
//  HELPERS
// ─────────────────────────────────────────────────────────────
function daysAgo(n) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().split("T")[0];
}

function corsHeaders(env) {
  const origin = env.ALLOWED_ORIGIN || "https://www.quranforyunus.com";
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function jsonError(env, message, status) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(env) },
  });
}
