import { parse as parseCookieHeader } from "cookie";
import type { Express, Request, Response } from "express";
import { SignJWT, jwtVerify } from "jose";
import { randomUUID } from "node:crypto";

/**
 * Server-side auth for the Re.Think frontend.
 *
 * The browser never sees the backend API key. This process holds it and
 * forwards the OAuth identity it verified in the `X-External-Id` header.
 * Two login paths are supported:
 *
 *  - Generic OAuth 2.0 authorization-code flow when OAUTH_* env vars exist.
 *  - A development sign-in (`/api/auth/login`) that is disabled in production
 *    unless ALLOW_DEV_LOGIN=true. It exists because no OAuth provider
 *    credentials are provisioned in this environment.
 */

export const SESSION_COOKIE = "rethink_session";
export const OAUTH_STATE_COOKIE = "rethink_oauth_state";

const BACKEND_URL = (process.env.RETHINK_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const SESSION_SECRET = process.env.SESSION_SECRET || process.env.MANUS_JWT_SECRET || "";
if (!SESSION_SECRET) {
  console.warn("[auth] SESSION_SECRET is not set; using an ephemeral development secret");
}
const secretKey = new TextEncoder().encode(
  SESSION_SECRET || "rethink-dev-session-secret-change-me"
);

export type SessionUser = {
  externalId: string;
  name: string;
  backendUserId: number;
  username: string;
};

const isProduction = process.env.NODE_ENV === "production";
const devLoginEnabled =
  process.env.ALLOW_DEV_LOGIN === "true" || !isProduction;

const oauthConfig = {
  authorizeUrl: process.env.OAUTH_AUTHORIZE_URL || "",
  tokenUrl: process.env.OAUTH_TOKEN_URL || "",
  userInfoUrl: process.env.OAUTH_USERINFO_URL || "",
  clientId: process.env.OAUTH_CLIENT_ID || "",
  clientSecret: process.env.OAUTH_CLIENT_SECRET || "",
  scope: process.env.OAUTH_SCOPE || "openid email profile",
  externalIdField: process.env.OAUTH_EXTERNAL_ID_FIELD || "sub",
  nameField: process.env.OAUTH_NAME_FIELD || "name",
};

export function oauthEnabled(): boolean {
  return Boolean(
    oauthConfig.authorizeUrl &&
      oauthConfig.tokenUrl &&
      oauthConfig.userInfoUrl &&
      oauthConfig.clientId &&
      oauthConfig.clientSecret
  );
}

function cookieOptions(req: Request) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: isProduction || req.protocol === "https",
    path: "/",
  };
}

export async function createSessionToken(user: SessionUser): Promise<string> {
  return new SignJWT({ ...user })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("7d")
    .sign(secretKey);
}

export async function readSession(req: Request): Promise<SessionUser | null> {
  const raw = parseCookieHeader(req.headers.cookie ?? "")[SESSION_COOKIE];
  if (!raw) return null;
  try {
    const { payload } = await jwtVerify(raw, secretKey);
    if (
      typeof payload.externalId !== "string" ||
      typeof payload.backendUserId !== "number" ||
      typeof payload.username !== "string"
    ) {
      return null;
    }
    return {
      externalId: payload.externalId,
      name: typeof payload.name === "string" ? payload.name : "",
      backendUserId: payload.backendUserId,
      username: payload.username,
    };
  } catch {
    return null;
  }
}

/** Resolve (or create) the backend user for a verified identity. */
async function resolveBackendUser(
  externalId: string,
  name?: string
): Promise<{ id: number; username: string }> {
  if (!process.env.RETHINK_API_KEY) {
    throw Object.assign(new Error("RETHINK_API_KEY is not configured on the server"), {
      status: 500,
    });
  }

  let response: globalThis.Response;
  try {
    response = await fetch(`${BACKEND_URL}/api/users/resolve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": process.env.RETHINK_API_KEY,
        "X-External-Id": externalId,
      },
      body: JSON.stringify({ external_id: externalId, username: name || undefined }),
    });
  } catch {
    throw Object.assign(new Error("Backend is unavailable"), { status: 503 });
  }

  if (!response.ok) {
    const detail = await response.text();
    throw Object.assign(
      new Error(`Backend rejected identity resolution (${response.status}): ${detail}`),
      { status: response.status === 403 ? 403 : 502 }
    );
  }

  const body = (await response.json()) as { id: number; username: string };
  return { id: body.id, username: body.username };
}

async function establishSession(
  req: Request,
  res: Response,
  externalId: string,
  name: string
): Promise<SessionUser> {
  const backendUser = await resolveBackendUser(externalId, name);
  const user: SessionUser = {
    externalId,
    name: name || backendUser.username,
    backendUserId: backendUser.id,
    username: backendUser.username,
  };
  const token = await createSessionToken(user);
  res.cookie(SESSION_COOKIE, token, { ...cookieOptions(req), maxAge: 7 * 24 * 3600 * 1000 });
  return user;
}

export function registerAuthRoutes(app: Express) {
  app.get("/api/auth/config", (_req, res) => {
    res.json({
      oauthEnabled: oauthEnabled(),
      devLoginEnabled,
      defaultExternalId: process.env.DEFAULT_EXTERNAL_ID || "",
    });
  });

  app.get("/api/auth/me", async (req, res) => {
    const user = await readSession(req);
    if (!user) {
      res.status(401).json({ detail: "Not authenticated" });
      return;
    }
    res.json({ user });
  });

  app.post("/api/auth/logout", (req, res) => {
    res.clearCookie(SESSION_COOKIE, cookieOptions(req));
    res.json({ status: "ok" });
  });

  // Development sign-in. This is NOT OAuth; it is the fallback when no OAuth
  // provider credentials are configured. It can be disabled explicitly.
  app.post("/api/auth/login", async (req, res) => {
    if (!devLoginEnabled) {
      res.status(404).json({ detail: "Development login is disabled" });
      return;
    }
    const externalId = String(req.body?.external_id || "").trim();
    const name = String(req.body?.name || "").trim();
    if (!externalId) {
      res.status(400).json({ detail: "external_id is required" });
      return;
    }
    try {
      const user = await establishSession(req, res, externalId, name);
      res.json({ user });
    } catch (error) {
      const status = (error as { status?: number }).status || 500;
      res.status(status).json({ detail: (error as Error).message });
    }
  });

  app.get("/api/auth/oauth/start", (req, res) => {
    if (!oauthEnabled()) {
      res.status(503).json({ detail: "OAuth is not configured on this server" });
      return;
    }
    const nonce = randomUUID();
    res.cookie(OAUTH_STATE_COOKIE, nonce, {
      ...cookieOptions(req),
      maxAge: 10 * 60 * 1000,
    });
    const redirectUri = `${req.protocol}://${req.get("host")}/api/auth/oauth/callback`;
    const url = new URL(oauthConfig.authorizeUrl);
    url.searchParams.set("client_id", oauthConfig.clientId);
    url.searchParams.set("redirect_uri", redirectUri);
    url.searchParams.set("response_type", "code");
    url.searchParams.set("scope", oauthConfig.scope);
    url.searchParams.set("state", nonce);
    res.redirect(302, url.toString());
  });

  app.get("/api/auth/oauth/callback", async (req, res) => {
    if (!oauthEnabled()) {
      res.status(503).json({ detail: "OAuth is not configured on this server" });
      return;
    }
    const code = typeof req.query.code === "string" ? req.query.code : "";
    const state = typeof req.query.state === "string" ? req.query.state : "";
    const expected = parseCookieHeader(req.headers.cookie ?? "")[OAUTH_STATE_COOKIE];
    if (!code || !state || !expected || state !== expected) {
      res.status(403).json({ detail: "Invalid OAuth state" });
      return;
    }
    res.clearCookie(OAUTH_STATE_COOKIE, cookieOptions(req));

    const redirectUri = `${req.protocol}://${req.get("host")}/api/auth/oauth/callback`;
    try {
      const tokenResponse = await fetch(oauthConfig.tokenUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
        body: new URLSearchParams({
          grant_type: "authorization_code",
          code,
          redirect_uri: redirectUri,
          client_id: oauthConfig.clientId,
          client_secret: oauthConfig.clientSecret,
        }),
      });
      if (!tokenResponse.ok) {
        throw new Error(`Token exchange failed (${tokenResponse.status})`);
      }
      const tokens = (await tokenResponse.json()) as { access_token?: string };
      if (!tokens.access_token) throw new Error("OAuth provider returned no access token");

      const userResponse = await fetch(oauthConfig.userInfoUrl, {
        headers: { Authorization: `Bearer ${tokens.access_token}`, Accept: "application/json" },
      });
      if (!userResponse.ok) {
        throw new Error(`User info request failed (${userResponse.status})`);
      }
      const profile = (await userResponse.json()) as Record<string, unknown>;
      const externalId = String(profile[oauthConfig.externalIdField] || "");
      const name = String(profile[oauthConfig.nameField] || "");
      if (!externalId) {
        throw new Error(`OAuth profile has no '${oauthConfig.externalIdField}' field`);
      }

      await establishSession(req, res, externalId, name);
      res.redirect(302, "/");
    } catch (error) {
      console.error("[oauth] callback failed:", (error as Error).message);
      res.status(502).json({ detail: (error as Error).message });
    }
  });
}
