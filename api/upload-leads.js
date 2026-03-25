const formidable = require("formidable");
const XLSX        = require("xlsx");
const nodemailer  = require("nodemailer");
const fs          = require("fs");

// Tell Vercel NOT to parse the body — formidable handles multipart
module.exports.config = { api: { bodyParser: false } };

// ── helpers ──────────────────────────────────────────────────────────────────

function parseForm(req) {
  return new Promise((resolve, reject) => {
    const form = formidable({ multiples: false, keepExtensions: true });
    form.parse(req, (err, fields, files) => {
      if (err) reject(err);
      else resolve({ fields, files });
    });
  });
}

function buildTransporter() {
  const user = process.env.EMAIL_USER;
  const pass = process.env.EMAIL_PASS;
  if (!user || !pass) throw new Error("EMAIL_USER or EMAIL_PASS environment variables are not set in Vercel.");
  return nodemailer.createTransport({
    host:   process.env.SMTP_HOST || "smtp.gmail.com",
    port:   Number(process.env.SMTP_PORT) || 587,
    secure: false,
    auth:   { user, pass },
  });
}

function parseLeadsFromFile(filePath, ext) {
  const wb = XLSX.readFile(filePath);
  const ws = wb.Sheets[wb.SheetNames[0]];
  return XLSX.utils.sheet_to_json(ws);
}

function normalizeKey(obj, ...keys) {
  for (const k of keys) {
    const found = Object.keys(obj).find(
      (key) => key.trim().toLowerCase() === k.toLowerCase()
    );
    if (found && obj[found]) return String(obj[found]).trim();
  }
  return null;
}

function buildText(name, company, niche, agency, sender) {
  return `Hi ${name},\n\nI came across ${company || "your company"} and wanted to reach out about ${niche}.\n\nAt ${agency}, we help businesses like yours grow through targeted email outreach and automation.\n\nWould you be open to a quick 15-minute call this week?\n\nBest,\n${sender}\n${agency}`;
}

function buildHtml(name, company, niche, agency, sender) {
  return `<!DOCTYPE html><html><body style="font-family:Inter,sans-serif;background:#0a0f0d;color:#e8f0ec;padding:32px;max-width:560px;margin:0 auto"><div style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:32px"><div style="width:40px;height:40px;background:linear-gradient(135deg,#ff6a00,#ff4500);border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-weight:700;color:#fff;margin-bottom:24px">NA</div><p style="margin:0 0 16px">Hi <strong>${name}</strong>,</p><p style="margin:0 0 16px;color:#8fa89a">I came across <strong style="color:#e8f0ec">${company || "your company"}</strong> and wanted to reach out about <strong style="color:#ff6a00">${niche}</strong>.</p><p style="margin:0 0 16px;color:#8fa89a">At <strong style="color:#e8f0ec">${agency}</strong>, we help businesses like yours grow through targeted email outreach and automation.</p><p style="margin:0 0 24px;color:#8fa89a">Would you be open to a quick 15-minute call this week?</p><p style="margin:0;color:#5a7066">Best,<br><strong style="color:#e8f0ec">${sender}</strong><br>${agency}</p></div></body></html>`;
}

// ── main handler ─────────────────────────────────────────────────────────────

module.exports = async function handler(req, res) {
  // CORS headers
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  let uploadedPath = null;

  try {
    // 1. Parse multipart upload
    const { files } = await parseForm(req);
    const fileEntry  = files.file || files.leads || Object.values(files)[0];
    if (!fileEntry) return res.status(400).json({ error: "No file uploaded." });

    const file       = Array.isArray(fileEntry) ? fileEntry[0] : fileEntry;
    uploadedPath     = file.filepath;

    // 2. Parse rows from CSV / XLSX
    const rows = parseLeadsFromFile(uploadedPath);
    if (!rows.length) return res.status(400).json({ error: "File is empty or has no valid rows." });

    // 3. Build SMTP transporter
    const transporter = buildTransporter();
    const senderName  = process.env.SENDER_NAME  || "NORML Agency";
    const agencyName  = process.env.AGENCY_NAME  || "NORML Agency";
    const fromAddress = process.env.EMAIL_USER;

    // 4. Send emails row by row
    const leads = [];
    let sent = 0, skipped = 0, failed = 0;
    const errors = [];

    for (const row of rows) {
      const email   = normalizeKey(row, "email", "Email", "email address", "Email Address");
      const name    = normalizeKey(row, "name", "Name", "full name", "Full Name") || "there";
      const company = normalizeKey(row, "company", "Company", "company name") || "";
      const niche   = normalizeKey(row, "niche", "solution", "interest", "service", "Solution", "Interest") || "your business";

      if (!email || !email.includes("@")) {
        skipped++;
        leads.push({ name, email: email || "—", company, niche, status: "skipped" });
        continue;
      }

      try {
        await transporter.sendMail({
          from:    `"${senderName}" <${fromAddress}>`,
          to:      email,
          subject: `Quick note for ${company || name}`,
          text:    buildText(name, company, niche, agencyName, senderName),
          html:    buildHtml(name, company, niche, agencyName, senderName),
        });
        sent++;
        leads.push({ name, email, company, niche, status: "sent" });
      } catch (err) {
        failed++;
        errors.push({ email, error: err.message });
        leads.push({ name, email, company, niche, status: "failed", error: err.message });
      }
    }

    return res.status(200).json({ success: true, total: rows.length, sent, skipped, failed, errors, leads });

  } catch (err) {
    return res.status(500).json({ error: err.message });
  } finally {
    if (uploadedPath && fs.existsSync(uploadedPath)) {
      try { fs.unlinkSync(uploadedPath); } catch (_) {}
    }
  }
};
