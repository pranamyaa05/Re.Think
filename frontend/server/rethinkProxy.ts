import type { Express, Request, Response } from "express";
import { readSession } from "./rethinkAuth";

/**
 * Same-origin proxy from the browser to the FastAPI backend.
 *
 * Security properties:
 *  - RETHINK_API_KEY is read from the server environment only; it never
 *    reaches the browser bundle or a client request.
 *  - The verified OAuth identity is attached as X-External-Id, and any
 *    client-supplied X-API-Key / X-External-Id headers are stripped.
 *  - The backend independently enforces that the identity owns the requested
 *    user_id, so a forged path cannot cross accounts.
 */

const BACKEND_URL = (process.env.RETHINK_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export function registerRethinkProxy(app: Express) {
  app.all("/api/rethink/*", async (req: Request, res: Response) => {
    const user = await readSession(req);
    if (!user) {
      res.status(401).json({ detail: "Not authenticated" });
      return;
    }

    if (!process.env.RETHINK_API_KEY) {
      res.status(500).json({ detail: "RETHINK_API_KEY is not configured on the server" });
      return;
    }

    const targetPath = req.originalUrl.replace(/^\/api\/rethink/, "/api");
    const hasBody = !["GET", "HEAD"].includes(req.method);
    const body =
      hasBody && req.body && Object.keys(req.body as object).length > 0
        ? JSON.stringify(req.body)
        : undefined;

    let upstream: globalThis.Response;
    try {
      upstream = await fetch(`${BACKEND_URL}${targetPath}`, {
        method: req.method,
        headers: {
          Accept: "application/json",
          ...(body ? { "Content-Type": "application/json" } : {}),
          "X-API-Key": process.env.RETHINK_API_KEY,
          "X-External-Id": user.externalId,
        },
        body,
        redirect: "manual",
      });
    } catch {
      // Network/DNS/timeout: surface a typed 503 the UI can render honestly.
      res.status(503).json({
        detail: "Backend unavailable",
        code: "backend_unavailable",
      });
      return;
    }

    const payload = Buffer.from(await upstream.arrayBuffer());
    const contentType = upstream.headers.get("content-type");
    if (contentType) res.setHeader("Content-Type", contentType);
    const retryAfter = upstream.headers.get("retry-after");
    if (retryAfter) res.setHeader("Retry-After", retryAfter);
    res.status(upstream.status).send(payload);
  });
}
