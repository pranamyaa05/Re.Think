import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError, authApi, type AuthConfig } from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const { login } = useAuth();
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [externalId, setExternalId] = useState("");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    authApi
      .config()
      .then((value) => {
        if (cancelled) return;
        setConfig(value);
        setExternalId(value.defaultExternalId || "");
      })
      .catch((err) => {
        if (!cancelled) setConfigError(err instanceof Error ? err.message : "Could not load auth config.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(externalId.trim(), name.trim() || undefined);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Sign-in failed.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-background px-5 py-10">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <img
            src="/rethink-icon.png"
            alt="Re.Think"
            className="mb-3 h-14 w-14 rounded-xl object-cover"
          />
          <CardTitle>Sign in to Re.Think</CardTitle>
          <CardDescription>
            Your progress, coaching sessions and reflections are tied to your identity.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {configError ? <Alert variant="destructive"><AlertDescription>{configError}</AlertDescription></Alert> : null}

          {config?.oauthEnabled ? (
            <Button className="w-full" asChild>
              <a href={authApi.oauthStartUrl}>Continue with OAuth</a>
            </Button>
          ) : null}

          {config?.devLoginEnabled ? (
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="external-id">OAuth identity</Label>
                <Input
                  id="external-id"
                  value={externalId}
                  onChange={(event) => setExternalId(event.target.value)}
                  placeholder="e.g. leetcode_Pranamyaa"
                  autoComplete="username"
                  required
                />
                <p className="text-xs text-muted-foreground">
                  This is the identity your OAuth session maps to. The server resolves it to a
                  backend user; it never trusts an id from the browser.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="display-name">Display name (optional)</Label>
                <Input
                  id="display-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Your name"
                />
              </div>
              {error ? (
                <Alert variant="destructive">
                  <AlertDescription className="whitespace-pre-wrap">{error}</AlertDescription>
                </Alert>
              ) : null}
              <Button type="submit" className="w-full" disabled={submitting || !externalId.trim()}>
                {submitting ? "Signing in…" : "Continue"}
              </Button>
              {!config.oauthEnabled ? (
                <p className="text-xs text-muted-foreground">
                  No OAuth provider credentials are configured on this server, so this
                  development sign-in is used instead. Configure OAUTH_* environment
                  variables to enable the real OAuth flow.
                </p>
              ) : null}
            </form>
          ) : null}

          {config && !config.oauthEnabled && !config.devLoginEnabled ? (
            <Alert variant="destructive">
              <AlertDescription>
                No sign-in method is enabled. Configure OAuth or set ALLOW_DEV_LOGIN=true.
              </AlertDescription>
            </Alert>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
