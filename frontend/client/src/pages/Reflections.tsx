import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, ApiError, type Reflection } from "@/lib/api";
import { EmptyState, ErrorState, LoadingBlock, showDateTime } from "@/components/PageState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

export default function Reflections() {
  const { user, logout } = useAuth();
  const userId = user?.backendUserId ?? null;
  const [from, setFrom] = useState(isoDaysAgo(30));
  const [to, setTo] = useState(isoDaysAgo(0));
  const [items, setItems] = useState<Reflection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    if (userId === null) return;
    setLoading(true);
    try {
      setItems(await api.reflections(userId, from, to));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) {
        await logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Could not load reflections.");
    } finally {
      setLoading(false);
    }
  }, [userId, from, to, logout]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleGenerate() {
    if (userId === null) return;
    setGenerating(true);
    setNotice(null);
    setError(null);
    try {
      const result = await api.generateReflection(userId, to);
      setNotice(
        result.status === "skipped"
          ? result.reason || "No reflection was generated."
          : `Reflection ${result.status}.`
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate a reflection.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Reflections</h1>
        <p className="text-sm text-muted-foreground">
          Daily notes grounded in the metrics stored for that date.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Date range</CardTitle>
          <CardDescription>Filters the list; generation targets the “to” date.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-4">
          <div className="space-y-2">
            <Label htmlFor="from">From</Label>
            <Input id="from" type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="to">To</Label>
            <Input id="to" type="date" value={to} onChange={(event) => setTo(event.target.value)} />
          </div>
          <Button variant="outline" onClick={() => void load()}>
            Apply
          </Button>
          <Button onClick={() => void handleGenerate()} disabled={generating}>
            {generating ? "Generating…" : `Generate for ${to}`}
          </Button>
        </CardContent>
      </Card>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {notice ? (
        <Alert>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      ) : null}

      {loading ? (
        <LoadingBlock rows={4} />
      ) : items.length === 0 ? (
        <EmptyState
          title="No reflections in this range"
          description="Generate one for a date with recorded activity."
        />
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <Card key={item.id}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-lg">{item.date}</CardTitle>
                  <span className="text-xs text-muted-foreground">
                    Generated {showDateTime(item.generated_at)}
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-sm">{item.content}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
