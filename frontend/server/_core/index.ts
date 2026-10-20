import "dotenv/config";
import express from "express";
import { createServer } from "http";
import { registerAuthRoutes } from "../rethinkAuth";
import { registerRethinkProxy } from "../rethinkProxy";
import { serveStatic, setupVite } from "./vite";

async function startServer() {
  const app = express();
  const server = createServer(app);

  app.use(express.json({ limit: "2mb" }));
  app.use(express.urlencoded({ limit: "2mb", extended: true }));

  app.get("/api/health", (_req, res) => res.json({ status: "ok", service: "rethink-web" }));

  // Session + OAuth routes, then the key-holding backend proxy.
  registerAuthRoutes(app);
  registerRethinkProxy(app);

  if (process.env.NODE_ENV === "development") {
    await setupVite(app, server);
  } else {
    serveStatic(app);
  }

  const port = Number(process.env.PORT || "3000");
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid PORT");
  server.on("error", (error) => {
    console.error("Server failed:", error.message);
    process.exit(1);
  });
  server.listen(port, "0.0.0.0", () => {
    console.log(`Re.Think web server listening on port ${port}`);
  });
}

startServer().catch((error) => {
  console.error(error);
  process.exit(1);
});
