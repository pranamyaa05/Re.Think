import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import {
  api,
  ApiError,
  type CoachSession,
  type CoachSessionListItem,
} from "@/lib/api";
import { EmptyState, ErrorState, LoadingBlock, showDateTime } from "@/components/PageState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export default function Coach() {
  const { user, logout } = useAuth();
  const userId = user?.backendUserId ?? null;

  const [sessions, setSessions] = useState<CoachSessionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [problemId, setProblemId] = useState("");
  const [creating, setCreating] = useState(false);

  const [selected, setSelected] = useState<CoachSession | null>(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);

  const loadSessions = useCallback(async () => {
    if (userId === null) return;
    setLoading(true);
    try {
      setSessions(await api.coachSessions(userId));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) {
        await logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Could not load coaching sessions.");
    } finally {
      setLoading(false);
    }
  }, [userId, logout]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  async function openSession(sessionId: number) {
    setSendError(null);
    setRetryAfter(null);
    try {
      setSelected(await api.coachSession(sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the session.");
    }
  }

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (userId === null) return;
    const parsed = Number(problemId);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      setError("Enter a numeric problem id.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const session = await api.createCoachSession(userId, parsed);
      setSelected(session);
      setProblemId("");
      await loadSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the session.");
    } finally {
      setCreating(false);
    }
  }

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !message.trim()) return;
    setSending(true);
    setSendError(null);
    setRetryAfter(null);
    try {
      const result = await api.sendCoachMessage(selected.id, message.trim());
      setSelected({
        ...selected,
        current_level: result.current_level,
        coach_mode: result.coach_mode,
        user_stated_approach: result.user_stated_approach,
        messages: [...selected.messages, result.coach_message],
      });
      setMessage("");
      await loadSessions();
    } catch (err) {
      if (err instanceof ApiError && err.isRateLimited) {
        setRetryAfter(err.retryAfterSeconds);
        setSendError(err.message);
      } else {
        setSendError(err instanceof Error ? err.message : "Could not send the message.");
      }
    } finally {
      setSending(false);
    }
  }

  async function handleConclude(outcome: "solved" | "gave_up") {
    if (!selected) return;
    try {
      const updated = await api.concludeCoachSession(selected.id, outcome);
      setSelected(updated);
      await loadSessions();
    } catch (err) {
      setSendError(err instanceof Error ? err.message : "Could not conclude the session.");
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Coach</h1>
        <p className="text-sm text-muted-foreground">
          Socratic coaching sessions. Hints never expose the full solution.
        </p>
      </div>

      {error ? <ErrorState message={error} onRetry={() => void loadSessions()} /> : null}

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Start a session</CardTitle>
              <CardDescription>Use a problem id from the Knowledge page.</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-3" onSubmit={handleCreate}>
                <div className="space-y-2">
                  <Label htmlFor="problem-id">Problem id</Label>
                  <Input
                    id="problem-id"
                    inputMode="numeric"
                    value={problemId}
                    onChange={(event) => setProblemId(event.target.value)}
                    placeholder="e.g. 42"
                    required
                  />
                </div>
                <Button type="submit" disabled={creating || !problemId.trim()}>
                  {creating ? "Starting…" : "Start session"}
                </Button>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Sessions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {loading ? (
                <LoadingBlock rows={3} />
              ) : sessions.length === 0 ? (
                <EmptyState title="No sessions yet" />
              ) : (
                sessions.map((session) => (
                  <button
                    key={session.id}
                    type="button"
                    onClick={() => void openSession(session.id)}
                    className="w-full rounded-md border border-border p-3 text-left transition-colors hover:bg-muted"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">
                        {session.problem_title || `Problem #${session.problem_id}`}
                      </span>
                      <Badge variant="outline">{session.outcome}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Level {session.current_level} · {session.coach_mode} ·{" "}
                      {showDateTime(session.last_activity_at)}
                    </p>
                  </button>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>
              {selected ? `Session #${selected.id}` : "Select a session"}
            </CardTitle>
            <CardDescription>
              {selected
                ? `Level ${selected.current_level} · ${selected.coach_mode} · ${selected.outcome}`
                : "Pick a session on the left, or start a new one."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!selected ? null : (
              <>
                <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
                  {selected.messages.length === 0 ? (
                    <EmptyState title="No messages yet" description="Send your first attempt to get a nudge." />
                  ) : (
                    selected.messages.map((hint) => (
                      <div
                        key={hint.id}
                        className={
                          hint.role === "user"
                            ? "ml-auto max-w-[85%] rounded-lg bg-secondary p-3 text-sm"
                            : "max-w-[85%] rounded-lg border border-border bg-card p-3 text-sm"
                        }
                      >
                        <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                          <span className="font-medium uppercase tracking-wide">{hint.role}</span>
                          {hint.hint_level !== null ? <span>level {hint.hint_level}</span> : null}
                          {hint.tier1_blocked ? <Badge variant="destructive">blocked</Badge> : null}
                        </div>
                        <p className="whitespace-pre-wrap">{hint.content}</p>
                      </div>
                    ))
                  )}
                </div>

                {sendError ? (
                  <Alert variant="destructive">
                    <AlertDescription>
                      <span className="whitespace-pre-wrap">{sendError}</span>
                      {retryAfter !== null ? (
                        <span className="mt-1 block text-xs">Retry after {retryAfter}s.</span>
                      ) : null}
                    </AlertDescription>
                  </Alert>
                ) : null}

                <form className="space-y-3" onSubmit={handleSend}>
                  <Textarea
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    placeholder="Describe your current approach…"
                    rows={3}
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit" disabled={sending || !message.trim()}>
                      {sending ? "Sending…" : "Send"}
                    </Button>
                    <Button type="button" variant="outline" onClick={() => void handleConclude("solved")}>
                      Mark solved
                    </Button>
                    <Button type="button" variant="ghost" onClick={() => void handleConclude("gave_up")}>
                      Give up
                    </Button>
                  </div>
                </form>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
