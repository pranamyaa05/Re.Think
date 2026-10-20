import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, ApiError, type Problem, type ProblemKnowledge } from "@/lib/api";
import { EmptyState, ErrorState, LoadingBlock, showDateTime } from "@/components/PageState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export default function Knowledge() {
  const { logout } = useAuth();
  const [problems, setProblems] = useState<Problem[]>([]);
  const [loadingProblems, setLoadingProblems] = useState(true);
  const [selectedId, setSelectedId] = useState<string>("");
  const [knowledge, setKnowledge] = useState<ProblemKnowledge | null>(null);
  const [loadingKnowledge, setLoadingKnowledge] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .problems(100)
      .then((rows) => {
        if (!cancelled) setProblems(rows);
      })
      .catch(async (err) => {
        if (err instanceof ApiError && err.isUnauthorized) {
          await logout();
          return;
        }
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load problems.");
      })
      .finally(() => {
        if (!cancelled) setLoadingProblems(false);
      });
    return () => {
      cancelled = true;
    };
  }, [logout]);

  const loadKnowledge = useCallback(async (problemId: number) => {
    setLoadingKnowledge(true);
    setError(null);
    setNotice(null);
    try {
      setKnowledge(await api.knowledge(problemId));
    } catch (err) {
      setKnowledge(null);
      if (err instanceof ApiError) {
        if (err.isUnauthorized) {
          await logout();
          return;
        }
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Could not load knowledge.");
      }
    } finally {
      setLoadingKnowledge(false);
    }
  }, [logout]);

  function handleSelect(value: string) {
    setSelectedId(value);
    const parsed = Number(value);
    if (Number.isInteger(parsed) && parsed > 0) void loadKnowledge(parsed);
  }

  async function handleVerify(status: "user_verified" | "user_rejected") {
    if (!knowledge) return;
    try {
      const updated = await api.verifyKnowledge(knowledge.id, status);
      setKnowledge(updated);
      setNotice(
        status === "user_verified"
          ? "Marked as verified. The coach may now use a fuller coaching mode."
          : "Marked as rejected. The coach stays cautious."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update verification.");
    }
  }

  const selectedProblem = problems.find((problem) => String(problem.id) === selectedId) || null;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Knowledge verification</h1>
        <p className="text-sm text-muted-foreground">
          Review the extracted editorial knowledge that grounds the coach. Verification is
          recorded per problem and changes the coach mode.
        </p>
      </div>

      {error ? <ErrorState message={error} /> : null}
      {notice ? (
        <Alert>
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Problem</CardTitle>
          <CardDescription>Pick a problem to inspect its stored knowledge.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {loadingProblems ? (
            <LoadingBlock rows={1} />
          ) : problems.length === 0 ? (
            <EmptyState title="No problems available" description="Sync a platform first." />
          ) : (
            <Select value={selectedId} onValueChange={handleSelect}>
              <SelectTrigger className="max-w-xl">
                <SelectValue placeholder="Select a problem" />
              </SelectTrigger>
              <SelectContent>
                {problems.map((problem) => (
                  <SelectItem key={problem.id} value={String(problem.id)}>
                    #{problem.id} · {problem.title}
                    {problem.difficulty_label
                      ? ` · ${problem.difficulty_label}`
                      : problem.rating
                        ? ` · ${problem.rating}`
                        : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          {selectedProblem ? (
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <Badge variant="outline" className="capitalize">
                {selectedProblem.platform}
              </Badge>
              <span>{selectedProblem.title}</span>
              <span>·</span>
              <span>
                {selectedProblem.difficulty_label
                  ? selectedProblem.difficulty_label
                  : selectedProblem.rating !== null
                    ? `Rating ${selectedProblem.rating}`
                    : "—"}
              </span>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {loadingKnowledge ? (
        <LoadingBlock rows={4} />
      ) : !knowledge ? (
        <EmptyState
          title="No knowledge loaded"
          description="Select a problem that has extracted editorial knowledge."
        />
      ) : (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>Extracted knowledge</CardTitle>
              <div className="flex items-center gap-2">
                <Badge variant="outline">{knowledge.validation_status}</Badge>
                <Badge variant="secondary">{knowledge.coach_mode || "unknown mode"}</Badge>
              </div>
            </div>
            <CardDescription>
              {knowledge.source_type} · {knowledge.extraction_method} · created{" "}
              {showDateTime(knowledge.created_at)}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5 text-sm">
            <Section title="Approach summary" body={knowledge.approach_summary} />
            <Section title="Key insight" body={knowledge.key_insight} />

            <div>
              <h3 className="mb-1 font-medium">Techniques</h3>
              {knowledge.techniques.length === 0 ? (
                <p className="text-muted-foreground">—</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {knowledge.techniques.map((technique) => (
                    <Badge key={technique} variant="secondary">
                      {technique}
                    </Badge>
                  ))}
                </div>
              )}
            </div>

            <div>
              <h3 className="mb-1 font-medium">Common pitfalls</h3>
              {knowledge.common_pitfalls.length === 0 ? (
                <p className="text-muted-foreground">—</p>
              ) : (
                <ul className="list-disc space-y-1 pl-5">
                  {knowledge.common_pitfalls.map((pitfall) => (
                    <li key={pitfall}>{pitfall}</li>
                  ))}
                </ul>
              )}
            </div>

            <div className="flex flex-wrap gap-2 pt-2">
              <Button onClick={() => void handleVerify("user_verified")}>Verify</Button>
              <Button variant="outline" onClick={() => void handleVerify("user_rejected")}>
                Reject
              </Button>
              {knowledge.editorial_url ? (
                <Button variant="ghost" asChild>
                  <a href={knowledge.editorial_url} target="_blank" rel="noreferrer">
                    Open source editorial
                  </a>
                </Button>
              ) : null}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Section({ title, body }: { title: string; body: string | null }) {
  return (
    <div>
      <h3 className="mb-1 font-medium">{title}</h3>
      <p className="whitespace-pre-wrap text-muted-foreground">{body || "—"}</p>
    </div>
  );
}
