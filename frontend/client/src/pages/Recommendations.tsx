import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, ApiError, type Recommendation } from "@/lib/api";
import { EmptyState, ErrorState, LoadingBlock, showDateTime } from "@/components/PageState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function Recommendations() {
  const { user, logout } = useAuth();
  const userId = user?.backendUserId ?? null;
  const [items, setItems] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    if (userId === null) return;
    setLoading(true);
    try {
      setItems(await api.recommendations(userId));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) {
        await logout();
        return;
      }
      setError(err instanceof Error ? err.message : "Could not load recommendations.");
    } finally {
      setLoading(false);
    }
  }, [userId, logout]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleGenerate() {
    if (userId === null) return;
    setGenerating(true);
    setNotice(null);
    setError(null);
    try {
      const result = await api.generateRecommendation(userId);
      if (result.status === "insufficient_data") {
        setNotice(
          "There is not enough data for a recommendation yet. Sync more submissions first."
        );
      } else if (result.status === "no_candidates") {
        setNotice("No suitable problem was found for the current topic targets.");
      } else {
        setNotice(result.reason || "Recommendation generated.");
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate a recommendation.");
    } finally {
      setGenerating(false);
    }
  }

  async function handleDismiss(item: Recommendation) {
    try {
      await api.dismissRecommendation(item.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not dismiss the recommendation.");
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Recommendations</h1>
          <p className="text-sm text-muted-foreground">
            Generated from your topic analytics. “Insufficient data” is reported honestly rather
            than filled with a guess.
          </p>
        </div>
        <Button onClick={() => void handleGenerate()} disabled={generating}>
          {generating ? "Generating…" : "Generate recommendation"}
        </Button>
      </div>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {notice ? (
        <Alert>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      ) : null}

      {loading ? (
        <LoadingBlock rows={3} />
      ) : items.length === 0 ? (
        <EmptyState
          title="No active recommendations"
          description="Generate one to get a targeted problem or study suggestion."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {items.map((item) => (
            <Card key={item.id}>
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="text-lg">{item.topic}</CardTitle>
                  <Badge variant="outline">{item.recommendation_type}</Badge>
                </div>
                <CardDescription>{item.reason}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {item.problem ? (
                  <div>
                    <div className="font-medium">{item.problem.title}</div>
                    <div className="text-muted-foreground">
                      {item.problem.rating !== null ? `Rating ${item.problem.rating}` : "Unrated"}
                      {item.problem.tags.length > 0 ? ` · ${item.problem.tags.join(", ")}` : ""}
                    </div>
                    {item.problem.url ? (
                      <a
                        className="text-sm underline underline-offset-4"
                        href={item.problem.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open problem
                      </a>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-muted-foreground">Study suggestion — no problem attached.</p>
                )}
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Created {showDateTime(item.created_at)}</span>
                  <Button variant="ghost" size="sm" onClick={() => void handleDismiss(item)}>
                    Dismiss
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
