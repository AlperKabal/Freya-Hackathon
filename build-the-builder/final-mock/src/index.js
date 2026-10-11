// The mock of the bank's services for the final case. Fill `routes` from the integration document (same paths,
// field names and shapes) and data.json from the test customers (same answers, HTTP status included).
// openapi.json describes the same services: the builder reads it from <address>/openapi.json.
import openapi from "./openapi.json";
import data from "./data.json";

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" } });

const routes = {
  // "POST /path/from/the/integration/document": (body, url, data) => json({ ... }, 200),
};

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/openapi.json") return json(openapi);
    if (url.pathname === "/") return json({ ok: true, routes: Object.keys(routes) });
    let body = {};
    if (request.method !== "GET") {
      try { body = await request.json(); } catch (e) { body = {}; }
    }
    const handler = routes[request.method + " " + url.pathname];
    if (!handler) return json({ error: "not found", path: url.pathname }, 404);
    return handler(body, url, data);
  },
};
