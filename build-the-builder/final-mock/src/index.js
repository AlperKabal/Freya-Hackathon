// The seven synthetic bank services. Recorded answers are served verbatim.
import records from "./data.json";
import openapi from "./openapi.json";

const customers = records.customers || [];
const byCustomer = new Map(customers.map((row) => [String(row.customerNo), row]));
const byCard = new Map();
for (const customer of customers) {
  for (const service of ["cards.balance", "statement.week.get", "statement.week.decide", "statement.week.change"]) {
    for (const card of Object.keys(customer.services?.[service] || {})) {
      if (!byCard.has(card)) byCard.set(card, customer);
    }
  }
}

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" },
});

function error(code, status, message, type = "ERROR") {
  const guid = "f0e1d2c3b4a5968778695a4b3c2dffff";
  return json({ result: { guid, returnCode: code, messageText: message, code,
    message, type, details: { guid, rootCause: null, errorOrigin: null } } }, status);
}

const missing = {
  "cards.list": ["FB_IVR_CHANNEL_102", 404, "Müşteriye ait geçerli kart bilgisi bulunamadı.", "WARNING"],
  "cards.balance": ["FB_IVR_CHANNEL_120", 404, "Kart bakiye servisi hatası: kart bulunamadı", "WARNING"],
  "statement.week.get": ["FB_IVR_CHANNEL_121", 404, "Kart bulunamadı", "WARNING"],
  "statement.pdf.send": ["FB_IVR_CHANNEL_107", 404, "Pdf dokümanı bulunamadı", "WARNING"],
};

function required(data, service) {
  const fields = {
    "cards.list": ["customerNo"],
    "cards.balance": ["cardNumber"],
    "statement.week.get": ["cardNumber"],
    "statement.week.decide": ["cardNumber", "newStatementWeek", "statementDay"],
    "statement.week.change": ["cardNumber", "newStatementWeek", "statementDay"],
    "contact.email.get": ["customerNo", "intAddressInfoType"],
    "statement.pdf.send": ["customerNo", "cardNumber", "currencyType", "statementDate", "emailAddress"],
  }[service] || [];
  return fields.find((key) => data[key] === undefined || data[key] === null || String(data[key]).trim() === "");
}

function findAnswer(service, data) {
  const customer = service === "cards.list" || service === "contact.email.get" || service === "statement.pdf.send"
    ? byCustomer.get(String(data.customerNo)) : byCard.get(String(data.cardNumber));
  if (!customer) return null;
  let answer = customer.services?.[service];
  if (["cards.balance", "statement.week.get", "statement.week.decide", "statement.week.change"].includes(service)) {
    answer = answer?.[String(data.cardNumber)];
  }
  if (service === "statement.week.decide" || service === "statement.week.change") {
    answer = answer?.[String(data.newStatementWeek)];
  }
  return answer || null;
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/openapi.json") return json(openapi);
    if (url.pathname === "/" || url.pathname === "/health") {
      return json({ ok: true, services: Object.keys(openapi.paths), customers: customers.length });
    }
    const service = url.pathname.replace(/^\/voice\/v1\//, "");
    if (request.method !== "POST" || !("/voice/v1/" + service in openapi.paths)) {
      return json({ error: "not found" }, 404);
    }
    let body;
    try { body = await request.json(); } catch { return error("INVALID_ARGUMENTS_ERROR", 400, "JSON body is required"); }
    const data = body?.data;
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return error("INVALID_ARGUMENTS_ERROR", 400, "data cannot be empty");
    }
    const absent = required(data, service);
    if (absent) return error("INVALID_ARGUMENTS_ERROR", 400, absent + " cannot be empty");
    const answer = findAnswer(service, data);
    if (!answer) return error(...(missing[service] || ["INVALID_ARGUMENTS_ERROR", 400, "No matching answer"]));
    const delay = Number(answer.delaySeconds ?? answer.gecikmeSaniye ?? 0);
    if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay * 1000));
    return json(answer.response, answer.http);
  },
};
