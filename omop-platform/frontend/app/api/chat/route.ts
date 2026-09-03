import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();
  try {
    const resp = await fetch(`${BACKEND_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(body),
    });
    return new Response(resp.body, {
      headers: { "Content-Type": "text/event-stream" },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: "Backend unavailable" }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}
