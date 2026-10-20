import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, ApiError, type PlatformLink } from "@/lib/api";
import { EmptyState, ErrorState, LoadingBlock, showDateTime } from "@/components/PageState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const POLL_MS = 2000;
const POLL_LIMIT_MS = 2 * 60 * 1000;

export default function Platforms() {
  const { user, logout } = useAuth();
  const userId = user?.backendUserId ?? null;
  const [links, setLinks] = useState<PlatformLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [platform, setPlatform] = useState("leetcode");
  const [handle, setHandle] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [creating, setCreating] = useState(false);

  const [pollingId, setPollingId] = useState<number | null>(null);
  const pollStartedAt = useRef<number>(0);

  const load = useCallback(async () => {
    if (userId === null) return;
    try {
      setLinks(await api.platforms(userId));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) {
        await logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Could not load platform links.");
    } finally {
      setLoading(false);
    }
  }, [userId, logout]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll the background sync. Stop on synced/failed or after the timeout.
  useEffect(() => {
    if (pollingId === null || userId === null) return;
    pollStartedAt.current = Date.now();

    const timer = window.setInterval(async () => {
      try {
        const link = await api.platformStatus(pollingId);
        setLinks((current) =>
          current.map((item) => (item.id === link.id ? link : item))
        );
        if (link.sync_status === "synced") {
          setPollingId(null);
          setNotice(`Sync complete for ${link.handle}. Analytics refreshed.`);
          // Refresh the analytics snapshot the dashboard reads.
          await api.analyticsSummary(userId);
        } else if (link.sync_status === "failed") {
          setPollingId(null);
        } else if (Date.now() - pollStartedAt.current > POLL_LIMIT_MS) {
          setPollingId(null);
          setNotice("Sync is taking longer than expected. Check the status again shortly.");
        }
      } catch (err) {
        setPollingId(null);
        setError(err instanceof Error ? err.message : "Could not poll sync status.");
      }
    }, POLL_MS);

    return () => window.clearInterval(timer);
  }, [pollingId, userId]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (userId === null) return;
    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      const link = await api.createPlatformLink(
        userId,
        platform,
        handle.trim(),
        authToken.trim() || undefined
      );
      setLinks((current) => [...current, link]);
      setHandle("");
      setAuthToken("");
      setNotice("Link created. Sync started in the background.");
      setPollingId(link.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the link.");
    } finally {
      setCreating(false);
    }
  }

  async function handleSync(link: PlatformLink) {
    setError(null);
    setNotice(null);
    try {
      const result = await api.syncPlatform(link.id);
      setNotice(
        `Fetched ${result.submissions_fetched} submissions (${result.submissions_newly_inserted} new) and ` +
          `${result.contests_fetched} contests (${result.contests_newly_inserted} new).`
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failed.");
      await load();
    }
  }

  async function handleUnlink(link: PlatformLink) {
    if (!window.confirm(`Unlink ${link.platform} / ${link.handle}?`)) return;
    try {
      await api.unlinkPlatform(link.id);
      setLinks((current) => current.filter((item) => item.id !== link.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not unlink this account.");
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Platforms &amp; Sync</h1>
        <p className="text-sm text-muted-foreground">
          Linking starts the sync in the background; this page polls the status and refreshes
          analytics when it finishes.
        </p>
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {notice ? (
        <Alert>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Link an account</CardTitle>
          <CardDescription>
            LeetCode links are validated against the platform before they are stored.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4 md:grid-cols-2" onSubmit={handleCreate}>
            <div className="space-y-2">
              <Label>Platform</Label>
              <Select value={platform} onValueChange={setPlatform}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="leetcode">LeetCode</SelectItem>
                  <SelectItem value="codeforces">Codeforces</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="handle">Handle</Label>
              <Input
                id="handle"
                value={handle}
                onChange={(event) => setHandle(event.target.value)}
                placeholder="your-handle"
                required
              />
            </div>
            {platform === "leetcode" ? (
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="cookie">LEETCODE_SESSION cookie (optional)</Label>
                <Input
                  id="cookie"
                  type="password"
                  value={authToken}
                  onChange={(event) => setAuthToken(event.target.value)}
                  placeholder="Paste a fresh session cookie to sync submissions"
                />
                <p className="text-xs text-muted-foreground">
                  Stored encrypted on the backend. Without it only public contest history syncs.
                </p>
              </div>
            ) : null}
            <div className="md:col-span-2">
              <Button type="submit" disabled={creating || !handle.trim()}>
                {creating ? "Creating…" : "Link and sync"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Linked accounts</CardTitle>
          <CardDescription>Status and errors are shown exactly as the backend reports them.</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingBlock rows={2} />
          ) : links.length === 0 ? (
            <EmptyState title="No accounts linked" description="Link LeetCode or Codeforces above to start syncing." />
          ) : (
            <div className="space-y-4">
              {links.map((link) => (
                <div key={link.id} className="rounded-lg border border-border p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium capitalize">{link.platform}</span>
                        <span className="text-muted-foreground">/</span>
                        <span>{link.handle}</span>
                        <StatusBadge status={link.sync_status} />
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Last synced: {showDateTime(link.last_synced_at)}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => void handleSync(link)}
                        disabled={link.sync_status === "syncing" || link.sync_status === "queued"}
                      >
                        Sync now
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => void handleUnlink(link)}>
                        Unlink
                      </Button>
                    </div>
                  </div>
                  {link.sync_status === "failed" && link.sync_error ? (
                    <Alert variant="destructive" className="mt-3">
                      <AlertDescription className="whitespace-pre-wrap font-mono text-xs">
                        {link.sync_error}
                      </AlertDescription>
                    </Alert>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatusBadge({ status }: { status: PlatformLink["sync_status"] }) {
  if (status === "synced") return <Badge>synced</Badge>;
  if (status === "failed") return <Badge variant="destructive">failed</Badge>;
  if (status === "syncing" || status === "queued")
    return <Badge variant="secondary">{status}</Badge>;
  return <Badge variant="outline">idle</Badge>;
}
