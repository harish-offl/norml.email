"use strict";
/**
 * send-emails.js — Optimized bulk email sender for NORML Agency
 *
 * PERFORMANCE IMPROVEMENTS over old version:
 * 1. Pooled SMTP transporter — reused across all sends, no new TCP handshake per email
 * 2. Controlled concurrency — sends MAX_CONCURRENCY emails simultaneously (default: 3)
 * 3. Templates built once, personalised per lead in memory (no repeated string construction)
 * 4. Retry logic — transient failures retried without blocking other leads
 * 5. No blocking operations inside the send loop
 *
 * NOTE: App-side processing targets ~1-3s per lead. Actual delivery time depends
 * on SMTP provider (Gmail) response latency which is outside our control.
 */

const nodemailer = require("nodemailer");

// ── Config from env ──────────────────────────────────────────────────────────
const SMTP_HOST      = process.env.SMTP_HOST     || process.env.SMTP_SERVER || "smtp.gmail.com";
const SMTP_PORT      = Number(process.env.SMTP_PORT) || 465;
const SMTP_SECURE    = process.env.SMTP_SECURE !== "false"; // default true for port 465
const EMAIL_USER     = process.env.EMAIL_USER    || process.env.EMAIL_ADDRESS || "";
const EMAIL_PASS     = process.env.EMAIL_PASS    || process.env.EMAIL_PASSWORD || "";
const SENDER_NAME    = process.env.SENDER_NAME   || "Ram Viswanth";
const AGENCY_NAME    = process.env.AGENCY_NAME   || "NORML Agency";
const FROM_EMAIL     = process.env.FROM_EMAIL    || EMAIL_USER;
const MAX_CONCURRENCY = Math.min(Number(process.env.MAX_CONCURRENCY) || 3, 5); // Gmail-safe max 5
const RETRY_COUNT    = Number(process.env.RETRY_COUNT)    || 1;
const RETRY_DELAY_MS = Number(process.env.RETRY_DELAY_MS) || 800;
const BATCH_DELAY_MS = Number(process.env.BATCH_DELAY_MS) || 0;

// ── Pooled transporter — created ONCE, reused for all sends ─────────────────
let _transporter = null;

function getTransporter() {
  if (_transporter) return _transporter;
  if (!EMAIL_USER || !EMAIL_PASS) {
    throw new Error("EMAIL_USER and EMAIL_PASS must be set in environment variables.");
  }
  // pool:true keeps SMTP connections alive across multiple sends
  // This eliminates TCP handshake overhead for every email
  _transporter = nodemailer.createTransport({
    host:   SMTP_HOST,
    port:   SMTP_PORT,
    secure: SMTP_SECURE,
    auth:   { user: EMAIL_USER, pass: EMAIL_PASS },
    pool:   true,           // KEY: reuse connections — major speed improvement
    maxConnections: MAX_CONCURRENCY,
    maxMessages:    500,    // messages per connection before cycling
    connectionTimeout: 10000,
    greetingTimeout:   8000,
    socketTimeout:     15000,
  });
  return _transporter;
}

// ── Template helpers — built once, personalised per lead ────────────────────
function buildSubject(lead) {
  const co = lead.company || lead.name || "your business";
  const svc = lead.niche || "our services";
  return `${svc} strategy for ${co}`;
}

function buildTextBody(lead) {
  const { name = "there", company = "your business", niche = "digital growth", industry = "your industry" } = lead;
  return [
    `Hi ${name},`,
    "",
    `As a professional in the ${industry} sector, you understand how important it is to stay ahead of competitors and maintain consistent growth.`,
    "",
    `With competition increasing and buyer behavior shifting online, many ${industry} businesses are finding it difficult to generate qualified leads and maintain strong visibility.`,
    "",
    `At ${AGENCY_NAME}, we help ${industry} businesses grow through ${niche} tailored to their target audience and market demand.`,
    "",
    "Here's what you can expect:",
    "",
    "- Increased qualified website traffic and online visibility",
    "- Improved lead generation from digital channels",
    "- Stronger brand authority in your market",
    "",
    `Would you be open to a quick 15-minute call to explore how ${niche} can help ${company} attract more clients?`,
    "",
    "Best regards,",
    SENDER_NAME,
  ].join("\n");
}

function buildHtmlBody(lead) {
  const { name = "there", company = "your business", niche = "digital growth", industry = "your industry" } = lead;
  const esc = s => String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  return `<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#fff;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 20px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">
<tr><td style="padding:0 0 20px;border-bottom:1px solid #e5e7eb">
  <span style="font-size:12px;font-weight:700;color:#ff6a00;letter-spacing:1px;text-transform:uppercase">${esc(AGENCY_NAME)}</span>
</td></tr>
<tr><td style="padding:28px 0 0">
  <p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#111">Hi <strong>${esc(name)}</strong>,</p>
  <p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#374151">As a professional in the <strong>${esc(industry)}</strong> sector, you understand how important it is to stay ahead of competitors and maintain consistent growth.</p>
  <p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#374151">With competition increasing and buyer behavior shifting online, many <strong>${esc(industry)}</strong> businesses are finding it difficult to generate qualified leads and maintain strong visibility.</p>
  <p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#374151">At <strong>${esc(AGENCY_NAME)}</strong>, we help <strong>${esc(industry)}</strong> businesses grow through <strong>${esc(niche)}</strong> tailored to their target audience and market demand.</p>
  <p style="margin:0 0 8px;font-size:15px;line-height:1.7;color:#374151">Here's what you can expect:</p>
  <table cellpadding="0" cellspacing="0" style="margin:0 0 16px">
    <tr><td style="padding:3px 0;font-size:15px;color:#374151">&#8212;&nbsp;Increased qualified website traffic and online visibility</td></tr>
    <tr><td style="padding:3px 0;font-size:15px;color:#374151">&#8212;&nbsp;Improved lead generation from digital channels</td></tr>
    <tr><td style="padding:3px 0;font-size:15px;color:#374151">&#8212;&nbsp;Stronger brand authority in your market</td></tr>
  </table>
  <p style="margin:0 0 24px;font-size:15px;line-height:1.7;color:#374151">Would you be open to a quick 15-minute call to explore how <strong>${esc(niche)}</strong> can help <strong>${esc(company)}</strong> attract more clients?</p>
  <p style="margin:0 0 2px;font-size:15px;color:#374151">Best regards,</p>
  <p style="margin:0 0 20px;font-size:15px;font-weight:700;color:#111">${esc(SENDER_NAME)}</p>
</td></tr>
<tr><td style="padding:20px 0 0;border-top:1px solid #e5e7eb">
  <p style="margin:0;font-size:11px;color:#9ca3af">To unsubscribe, reply with "unsubscribe".</p>
</td></tr>
</table></td></tr></table></body></html>`;
}

// ── Retry helper ─────────────────────────────────────────────────────────────
async function sendWithRetry(transporter, mailOptions, retries = RETRY_COUNT) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      await transporter.sendMail(mailOptions);
      return; // success
    } catch (err) {
      const isTransient = /ECONNRESET|ETIMEDOUT|ECONNREFUSED|421|450|451|452/.test(err.message);
      if (!isTransient || attempt === retries) throw err;
      // Wait before retry — exponential backoff
      await new Promise(r => setTimeout(r, RETRY_DELAY_MS * (attempt + 1)));
    }
  }
}

// ── Concurrency limiter — runs N tasks in parallel ───────────────────────────
async function runConcurrent(tasks, concurrency) {
  const results = [];
  let idx = 0;

  async function worker() {
    while (idx < tasks.length) {
      const i = idx++;
      results[i] = await tasks[i]();
    }
  }

  // Launch `concurrency` workers simultaneously
  const workers = Array.from({ length: Math.min(concurrency, tasks.length) }, worker);
  await Promise.all(workers);
  return results;
}

// ── Main handler ─────────────────────────────────────────────────────────────
module.exports = async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  // Parse body
  let body = req.body;
  if (!body) {
    try {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      body = JSON.parse(Buffer.concat(chunks).toString());
    } catch (_) { body = {}; }
  }

  const { leads } = body;
  if (!Array.isArray(leads) || !leads.length) {
    return res.status(400).json({ error: "No leads provided." });
  }

  // Get pooled transporter (created once, reused)
  let transporter;
  try {
    transporter = getTransporter();
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }

  const batchStart = Date.now();
  let sent = 0, failed = 0, skipped = 0;
  const errors  = [];
  const results = [];

  // Build one task per lead — executed concurrently
  const tasks = leads.map(lead => async () => {
    const { name = "there", email, company = "", niche = "", industry = "" } = lead;

    if (!email || !email.includes("@")) {
      skipped++;
      results.push({ email, status: "skipped" });
      return;
    }

    const mailOptions = {
      from:    `"${SENDER_NAME}" <${FROM_EMAIL}>`,
      to:      email,
      subject: buildSubject(lead),
      text:    buildTextBody(lead),
      html:    buildHtmlBody(lead),
    };

    try {
      await sendWithRetry(transporter, mailOptions);
      sent++;
      results.push({ email, status: "sent" });
      if (BATCH_DELAY_MS > 0) await new Promise(r => setTimeout(r, BATCH_DELAY_MS));
    } catch (err) {
      failed++;
      errors.push({ email, error: err.message });
      results.push({ email, status: "failed", error: err.message });
    }
  });

  // Run with controlled concurrency — KEY performance improvement
  await runConcurrent(tasks, MAX_CONCURRENCY);

  const elapsed = ((Date.now() - batchStart) / 1000).toFixed(2);
  console.log(`[send-emails] total=${leads.length} sent=${sent} failed=${failed} skipped=${skipped} elapsed=${elapsed}s concurrency=${MAX_CONCURRENCY}`);

  return res.status(200).json({
    success: true,
    total:   leads.length,
    sent, failed, skipped,
    elapsed_seconds: parseFloat(elapsed),
    errors,
    results,
  });
};
