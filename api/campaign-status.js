export default function handler(req, res) {
  // Returns idle status when running on Vercel (no Python backend)
  return res.status(200).json({
    status: "idle",
    message: "Campaign engine runs via the Python backend locally.",
    total: 0, processed: 0, sent: 0,
    skipped: 0, failed: 0, remaining: 0,
    elapsed_seconds: null, started_at: null, finished_at: null,
  });
}
