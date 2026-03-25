module.exports = function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  return res.status(200).json({
    status: "idle", message: "Ready.", total: 0,
    processed: 0, sent: 0, skipped: 0, failed: 0,
    remaining: 0, elapsed_seconds: null, started_at: null, finished_at: null,
  });
};
