import formidable from "formidable";
import * as XLSX from "xlsx";
import nodemailer from "nodemailer";
import fs from "fs";

// Disable Vercel's default body parser — formidable handles multipart
export const config = { api: { bodyParser: false } };

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
  if (!user || !pass) throw new Error("EMAIL_USER or EMAIL_PASS env vars not set.");
  return nodemailer.createTransport({
    host: process.env.SMTP_HOST || "smtp.gmail.com",
    port: Number(process.env.SMTP_PORT) || 587,
    secure: false,
    auth: { user, pass },
  });
}

function parseLeadsFromFile(filePath, ext) {
  if (ext === ".csv") {
    const wb = XLSX.readFile(filePath, { type: "file" });
    const ws = wb.Sheets[wb.SheetNames[0]];
    return XLSX.utils.sheet_to_json(ws);
  }
  if (ext === ".xlsx" || ext === ".xls") {
    const wb = XLSX.readFile(filePath);
    const ws = wb.Sheets[wb.SheetNames[0]];
    return XLSX.utils.sheet_to_json(ws);
  }
  throw new Error("Unsupported file type. Upload a .csv or .xlsx file.");
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

// ── handler ──────────────────────────────────────────────────────────────────

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  let uploadedPath = null;

  try {
    // 1. Parse multipart form
    const { files } = await parseForm(req);
    const fileEntry = files.file || files.leads || Object.values(files)[0];
    if (!fileEntry) return res.status(400).json({ error: "No file uploaded." });

    const file = Array.isArray(fileEntry) ? fileEntry[0] : fileEntry;
    uploadedPath = file.filepath;
    const ext = (file.originalFilename || "").slice(
      (file.originalFilename || "").lastIndexOf(".")
    ).toLowerCase();

    // 2. Parse leads
    const rows = parseLeadsFromFile(uploadedPath, ext);
    if (!rows.length) return res.status(400).json({ error: "File is empty or has no valid rows." });

    // 3. Build transporter
    const transporter = buildTransporter();

    // 4. Send emails
    const results = { sent: 0, skipped: 0, failed: 0, errors: [] };
    const senderName  = process.env.SENDER_NAME  || "NORML Agency";
    const agencyName  = process.env.AGENCY_NAME  || "NORML Agency";
    const fromAddress = process.env.EMAIL_USER;

    for (const row of rows) {
      const email   = normalizeKey(row, "email", "Email", "email address", "Email Address");
      const name    = normalizeKey(row, "name", "Name", "full name", "Full Name") || "there";
      const company = normalizeKey(row, "company", "Company", "company name") || "";
      const niche   = normalizeKey(row, "niche", "solution", "interest", "service") || "your business";

      if (!email || !email.includes("@")) { results.skipped++; continue; }

      try {
        await transporter.sendMail({
          from: `"${senderName}" <${fromAddress}>`,
          to: email,
          subject: `Quick note for ${company || name}`,
          text: buildPlainText(name, company, niche, agencyName, senderName),
          html: buildHtml(name, company, niche, agencyName, senderName),
        });
        results.sent++;
      } catch (err) {
        results.failed++;
        results.errors.push({ email, error: err.message });
      }
    }

    return res.status(200).json({
      success: true,
      total: rows.length,
      ...results,
    });

  } catch (err) {
    return res.status(500).json({ error: err.message });
  } finally {
    if (uploadedPath && fs.existsSync(uploadedPath)) {
      fs.unlinkSync(uploadedPath);
    }
  }
}

// ── email templates ───────────────────────────────────────────────────────────

function buildPlainText(name, company, niche, agency, sender) {
  return `Hi ${name},

I came across ${company || "your company"} and wanted to reach out about ${niche}.

At ${agency}, we help businesses like yours grow through targeted email outreach and automation.

Would you be open to a quick 15-minute call this week?

Best,
${sender}
${agency}`;
}

function buildHtml(name, company, niche, agency, sender) {
  return `<!DOCTYPE html>
<html>
<body style="font-family:Inter,sans-serif;background:#0a0f0d;color:#e8f0ec;padding:32px;max-width:560px;margin:0 auto">
  <div style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:32px">
    <div style="width:40px;height:40px;background:linear-gradient(135deg,#ff6a00,#ff4500);border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;margin-bottom:24px">NA</div>
    <p style="margin:0 0 16px">Hi <strong>${name}</strong>,</p>
    <p style="margin:0 0 16px;color:#8fa89a">I came across <strong style="color:#e8f0ec">${company || "your company"}</strong> and wanted to reach out about <strong style="color:#ff6a00">${niche}</strong>.</p>
    <p style="margin:0 0 16px;color:#8fa89a">At <strong style="color:#e8f0ec">${agency}</strong>, we help businesses like yours grow through targeted email outreach and automation.</p>
    <p style="margin:0 0 24px;color:#8fa89a">Would you be open to a quick 15-minute call this week?</p>
    <p style="margin:0;color:#5a7066">Best,<br><strong style="color:#e8f0ec">${sender}</strong><br>${agency}</p>
  </div>
</body>
</html>`;
}
