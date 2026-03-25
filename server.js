const fs   = require("fs");
const path = require("path");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css":  "text/css; charset=utf-8",
  ".js":   "application/javascript; charset=utf-8",
  ".json": "application/json",
  ".png":  "image/png",
  ".jpg":  "image/jpeg",
  ".svg":  "image/svg+xml",
  ".ico":  "image/x-icon",
};

function serveFile(res, filePath) {
  if (!fs.existsSync(filePath)) return false;
  const ext  = path.extname(filePath).toLowerCase();
  const mime = MIME[ext] || "application/octet-stream";
  res.setHeader("Content-Type", mime);
  res.setHeader("Cache-Control", "public, max-age=3600");
  res.status(200).send(fs.readFileSync(filePath));
  return true;
}

module.exports = function handler(req, res) {
  const url = req.url || "/";

  // ── API routes: inform client the Python backend must run separately ──
  if (url.startsWith("/api/")) {
    res.setHeader("Content-Type", "application/json");
    return res.status(503).json({
      error: "API unavailable on Vercel static deployment.",
      info:  "Run the Python FastAPI backend locally: python main.py --serve",
      docs:  "https://github.com/harish-offl/automation---norml"
    });
  }

  const base = path.join(__dirname, "frontend");

  // ── /frontend/styles.css etc ──
  if (url.startsWith("/frontend/")) {
    const rel  = url.replace("/frontend/", "");
    const file = path.join(base, rel);
    if (serveFile(res, file)) return;
  }

  // ── root → index.html ──
  const indexPath = path.join(base, "index.html");
  if (serveFile(res, indexPath)) return;

  res.status(404).send("Not found");
};
