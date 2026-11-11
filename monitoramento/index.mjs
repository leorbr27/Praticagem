import pg from "pg";
import webpush from "web-push";
import { parseTriggerDelivery } from "@neon/functions/triggers";

const { Pool } = pg;
const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 3 });
const ALLOWED_ORIGIN = "https://leorbr27.github.io";
const json = (data, status = 200, extra = {}) => new Response(JSON.stringify(data), {
  status,
  headers: { "Content-Type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": ALLOWED_ORIGIN, "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Cache-Control": "no-store", ...extra }
});
const norm = value => String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toUpperCase();
const shipKey = row => [row.navio,row.data,row.hora,row.tipo,row.porto,row.berco].map(norm).join("|");

const xmlEscape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"
}[char]));

function rssDate(row, fallback) {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(row.data ?? ""));
  const time = /^(\d{2}):(\d{2})$/.exec(String(row.hora ?? ""));
  if (match && time) {
    const [, day, month, year] = match;
    const [, hour, minute] = time;
    const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute)));
    if (!Number.isNaN(date.getTime())) return date.toUTCString();
  }
  return new Date(fallback || Date.now()).toUTCString();
}

async function rssResponse() {
  const subscriptions = await pool.query(
    "SELECT DISTINCT unnest(monitored_ships) AS ship FROM push_subscriptions WHERE cardinality(monitored_ships) > 0"
  );
  const monitored = new Set(subscriptions.rows.map(row => norm(row.ship)).filter(Boolean));
  let rows = [];
  let updatedAt = new Date().toISOString();

  if (monitored.size) {
    const response = await fetch("https://raw.githubusercontent.com/leorbr27/Praticagem/main/manobras.json?ts=" + Date.now(), { cache: "no-store" });
    if (!response.ok) throw new Error("Could not read manobras.json for RSS: HTTP " + response.status);
    const payload = await response.json();
    updatedAt = payload.atualizado_em || updatedAt;
    rows = (Array.isArray(payload.manobras) ? payload.manobras : [])
      .filter(row => monitored.has(norm(row.navio)));
  }

  const items = rows.map(row => {
    const title = [row.navio, row.situacao, row.data, row.hora].filter(Boolean).join(" — ");
    const description = [
      "Navio: " + (row.navio || "Não identificado"),
      "Situação: " + (row.situacao || "Não identificada"),
      "Data: " + (row.data || "—"),
      "Hora: " + (row.hora || "—"),
      "Tipo: " + (row.tipo || "—"),
      "Porto: " + (row.porto || "—"),
      "Berço: " + (row.berco || "—")
    ].join(" | ");
    const guid = shipKey(row) + "|" + norm(row.situacao);
    return "    <item>\n" +
      "      <title>" + xmlEscape(title) + "</title>\n" +
      "      <description>" + xmlEscape(description) + "</description>\n" +
      "      <guid isPermaLink=\"false\">" + xmlEscape(guid) + "</guid>\n" +
      "      <pubDate>" + rssDate(row, updatedAt) + "</pubDate>\n" +
      "      <link>https://leorbr27.github.io/Praticagem/index.html</link>\n" +
      "    </item>";
  }).join("\n");

  const xml = '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<rss version="2.0">\n  <channel>\n' +
    '    <title>Praticagem — Navios monitorados</title>\n' +
    '    <link>https://leorbr27.github.io/Praticagem/index.html</link>\n' +
    '    <description>Eventos exclusivamente dos navios selecionados para monitoramento no Praticagem.</description>\n' +
    '    <language>pt-BR</language>\n' +
    '    <lastBuildDate>' + new Date(updatedAt).toUTCString() + '</lastBuildDate>\n' +
    '    <ttl>5</ttl>\n' + items + '\n' +
    '  </channel>\n</rss>';

  return new Response(xml, {
    status: 200,
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-store, max-age=0"
    }
  });
}

function configurePush() {
  if (!process.env.VAPID_PUBLIC_KEY || !process.env.VAPID_PRIVATE_KEY || !process.env.VAPID_SUBJECT) return false;
  webpush.setVapidDetails(process.env.VAPID_SUBJECT, process.env.VAPID_PUBLIC_KEY, process.env.VAPID_PRIVATE_KEY);
  return true;
}

async function checkShips() {
  const activeResult = await pool.query(
    "SELECT COUNT(*)::int AS total FROM push_subscriptions WHERE cardinality(monitored_ships) > 0"
  );
  if (activeResult.rows[0]?.total === 0) {
    return { ok: true, skipped: true, reason: "no_monitored_ships", checkedAt: new Date().toISOString() };
  }
  if (!configurePush()) throw new Error("VAPID keys not configured");
  const response = await fetch("https://raw.githubusercontent.com/leorbr27/Praticagem/main/manobras.json?ts=" + Date.now(), { cache: "no-store" });
  if (!response.ok) throw new Error("Could not read manobras.json: HTTP " + response.status);
  const payload = await response.json();
  const rows = Array.isArray(payload.manobras) ? payload.manobras : [];
  const oldResult = await pool.query("SELECT ship_key, ship_name, situation, details FROM ship_situation_snapshot");
  const old = new Map(oldResult.rows.map(r => [r.ship_key, r]));
  const currentKeys = new Set();
  let changes = 0;
  for (const row of rows) {
    if (!row.navio) continue;
    const key = shipKey(row);
    currentKeys.add(key);
    const situation = String(row.situacao ?? "Não identificada");
    const previous = old.get(key);
    await pool.query(
      "INSERT INTO ship_situation_snapshot(ship_key,ship_name,situation,details,checked_at) VALUES($1,$2,$3,$4::jsonb,NOW()) ON CONFLICT(ship_key) DO UPDATE SET ship_name=EXCLUDED.ship_name,situation=EXCLUDED.situation,details=EXCLUDED.details,checked_at=NOW()",
      [key, row.navio, situation, JSON.stringify(row)]
    );
    if (!previous || norm(previous.situation) === norm(situation)) continue;
    const subscribers = await pool.query("SELECT id, endpoint, subscription FROM push_subscriptions WHERE $1 = ANY(monitored_ships)", [norm(row.navio)]);
    for (const subscriber of subscribers.rows) {
      try {
        await webpush.sendNotification(subscriber.subscription, JSON.stringify({
          title: "Praticagem: situação alterada",
          body: row.navio + " · " + (row.berco || "Berço não informado") + "\n" + previous.situation + " → " + situation,
          tag: "praticagem-" + key,
          url: "https://leorbr27.github.io/Praticagem/index.html"
        }));
        await pool.query("UPDATE push_subscriptions SET last_success_at=NOW(),last_error=NULL WHERE id=$1", [subscriber.id]);
        changes++;
      } catch (error) {
        const statusCode = error?.statusCode;
        await pool.query("UPDATE push_subscriptions SET last_error=$2 WHERE id=$1", [subscriber.id, String(error?.message ?? error).slice(0,1000)]);
        if (statusCode === 404 || statusCode === 410) await pool.query("DELETE FROM push_subscriptions WHERE id=$1", [subscriber.id]);
      }
    }
  }
  await pool.query("INSERT INTO push_service_state(key,value,updated_at) VALUES('last_check',$1::jsonb,NOW()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()", [JSON.stringify({ checkedAt: new Date().toISOString(), rows: rows.length, changesSent: changes, sourceUpdatedAt: payload.atualizado_em ?? null })]);
  return { ok: true, rows: rows.length, changesSent: changes, checkedAt: new Date().toISOString() };
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const origin = request.headers.get("origin");
    if (request.method === "GET" && url.pathname.replace(/\/+$/, "").endsWith("/rss")) {
      try { return await rssResponse(); } catch (error) { console.error("praticagem RSS error", error); return new Response("RSS indisponível", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } }); }
    }
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: { "Access-Control-Allow-Origin": ALLOWED_ORIGIN, "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400" } });
    if (url.pathname.endsWith("/cron")) { if (origin) return json({ error: "Origin not allowed" }, 403); } else if (origin !== ALLOWED_ORIGIN) return json({ error: "Origin not allowed" }, 403);
    try {
      if (request.method === "GET" && url.pathname.endsWith("/vapid-public-key")) {
        if (!process.env.VAPID_PUBLIC_KEY) return json({ error: "Push service not configured" }, 503);
        return json({ publicKey: process.env.VAPID_PUBLIC_KEY });
      }
      if (request.method === "POST" && url.pathname.endsWith("/subscribe")) {
        const body = await request.json();
        if (!body.subscription?.endpoint || !Array.isArray(body.monitoredShips)) return json({ error: "Invalid subscription" }, 400);
        const ships = [...new Set(body.monitoredShips.map(norm).filter(Boolean))];
        await pool.query(
          "INSERT INTO push_subscriptions(endpoint,subscription,monitored_ships,updated_at) VALUES($1,$2::jsonb,$3,NOW()) ON CONFLICT(endpoint) DO UPDATE SET subscription=EXCLUDED.subscription,monitored_ships=EXCLUDED.monitored_ships,updated_at=NOW(),last_error=NULL",
          [body.subscription.endpoint, JSON.stringify(body.subscription), ships]
        );
        return json({ ok: true, monitoredShips: ships.length });
      }
      if (request.method === "POST" && url.pathname.endsWith("/clear-other-subscriptions")) {
        const body = await request.json();
        if (!body.endpoint || typeof body.endpoint !== "string") return json({ error: "Missing current device endpoint" }, 400);
        const removed = await pool.query(
          "DELETE FROM push_subscriptions WHERE endpoint <> $1 RETURNING id",
          [body.endpoint]
        );
        return json({ ok: true, removed: removed.rowCount ?? removed.rows.length, keptCurrentDevice: true });
      }
      if (request.method === "POST" && url.pathname.endsWith("/unsubscribe")) {
        const body = await request.json();
        if (!body.endpoint) return json({ error: "Missing endpoint" }, 400);
        await pool.query("DELETE FROM push_subscriptions WHERE endpoint=$1", [body.endpoint]);
        return json({ ok: true });
      }
      if (request.method === "POST" && url.pathname.endsWith("/cron")) {
        const parsed = await parseTriggerDelivery(request);
        if (!parsed.ok || parsed.invocation.type !== "schedule") return json({ error: "Unauthorized trigger" }, 401);
        return json(await checkShips());
      }
      if (request.method === "GET" && url.pathname.endsWith("/health")) return json({ ok: true, service: "praticagem-push" });
      return json({ error: "Not found" }, 404);
    } catch (error) {
      console.error("praticagem push error", error);
      return json({ error: "Internal service error", detail: String(error?.message ?? error).slice(0,500) }, 500);
    }
  }
};
