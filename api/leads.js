export default function handler(req, res) {
  if (req.method === "GET") {
    // No DB on Vercel — return empty list
    return res.status(200).json([]);
  }
  return res.status(405).json({ error: "Method not allowed" });
}
