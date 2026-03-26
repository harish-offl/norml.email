"use strict";
const nodemailer = require("nodemailer");

function buildTransporter() {
  const user = process.env.EMAIL_USER || process.env.EMAIL_ADDRESS;
  const pass = process.env.EMAIL_PASS || process.env.EMAIL_PASSWORD;
  if (!user || !pass) throw new Error("Email credentials not set. Add EMAIL_USER and EMAIL_PASS in Vercel environment variables.");
  return nodemailer.createTransport({
    host:   process.env.SMTP_HOST || process.env.SMTP_SERVER || "smtp.gmail.com",
    port:   Number(process.env.SMTP_PORT) || 587,
    secure: false,
    auth:   { user, pass },
  });
}

function textBody(name, company, niche, agency, sender) {
  return `Hi ${name},

I came across ${company || "your company"} and wanted to reach out regarding ${niche || "your services"}.

At ${agency}, we specialise in helping businesses like yours grow through targeted email outreach and automation — saving time while generating consistent leads.

Would you be open to a quick 15-minute call this week to explore if there's a fit?

Best regards,
${sender}
${agency}

---
To unsubscribe, reply with "unsubscribe".`;
}

function htmlBody(name, company, niche, agency, sender) {
  return `<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:Arial,Helvetica,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff">
    <tr><td align="center" style="padding:40px 20px">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">
        <tr><td style="padding:0 0 24px 0;border-bottom:1px solid #e5e7eb">
          <span style="font-size:13px;font-weight:700;color:#ff6a00;letter-spacing:1px;text-transform:uppercase">${agency}</span>
        </td></tr>
        <tr><td style="padding:32px 0 0 0">
          <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#111827">Hi <strong>${name}</strong>,</p>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#374151">I came across <strong>${company || "your company"}</strong> and wanted to reach out regarding <strong>${niche || "your services"}</strong>.</p>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#374151">At <strong>${agency}</strong>, we specialise in helping businesses like yours grow through targeted email outreach and automation — saving time while generating consistent leads.</p>
          <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#374151">Would you be open to a quick 15-minute call this week to explore if there's a fit?</p>
          <p style="margin:0 0 4px;font-size:15px;line-height:1.6;color:#374151">Best regards,</p>
          <p style="margin:0 0 2px;font-size:15px;font-weight:700;color:#111827">${sender}</p>
          <p style="margin:0;font-size:14px;color:#6b7280">${agency}</p>
        </td></tr>
        <tr><td style="padding:32px 0 0 0;border-top:1px solid #e5e7eb;margin-top:32px">
          <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.5">You received this email because your business was identified as a potential fit for our services. To unsubscribe, simply reply with "unsubscribe".</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;
}

module.exports = async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

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
    return res.status(400).json({ error: "No leads provided. Pass { leads: [...] } in the request body." });
  }

  const senderName = process.env.SENDER_NAME || "Annamalai";
  const agencyName = process.env.AGENCY_NAME || "Arrise Digital";
  const fromAddr   = process.env.EMAIL_USER  || process.env.EMAIL_ADDRESS;

  let transporter;
  try { transporter = buildTransporter(); }
  catch (err) { return res.status(500).json({ error: err.message }); }

  let sent = 0, failed = 0, skipped = 0;
  const errors  = [];
  const results = [];

  for (const lead of leads) {
    const { name = "there", email, company = "", niche = "" } = lead;
    if (!email || !email.includes("@")) {
      skipped++;
      results.push({ email, status: "skipped" });
      continue;
    }
    try {
      await transporter.sendMail({
        from:    `"${senderName}" <${fromAddr}>`,
        to:      email,
        subject: `Quick note for ${company || name}`,
        text:    textBody(name, company, niche, agencyName, senderName),
        html:    htmlBody(name, company, niche, agencyName, senderName),
      });
      sent++;
      results.push({ email, status: "sent" });
    } catch (err) {
      failed++;
      errors.push({ email, error: err.message });
      results.push({ email, status: "failed", error: err.message });
    }
  }

  return res.status(200).json({
    success: true,
    total:   leads.length,
    sent, failed, skipped, errors, results,
  });
};
