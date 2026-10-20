import { Route, Switch } from "wouter";
import AppShell from "@/components/AppShell";
import Dashboard from "@/pages/Dashboard";
import Home from "@/pages/Home";
import Platforms from "@/pages/Platforms";
import Coach from "@/pages/Coach";
import Recommendations from "@/pages/Recommendations";
import Reflections from "@/pages/Reflections";
import Contests from "@/pages/Contests";
import Knowledge from "@/pages/Knowledge";
import LoginPage from "@/pages/Login";
import NotFound from "@/pages/NotFound";

export default function App() {
  return (
    <Switch>
      {/* Public landing page. It shows the signed-in learner's own data when
          there is a session, and honest placeholders when there is not. */}
      <Route path="/" component={Home} />
      <Route path="/login" component={LoginPage} />
      <Route path="/404" component={NotFound} />
      {/* Everything below needs a session; AppShell renders the sign-in page
          when there is none. */}
      <Route>
        <AppShell>
          <Switch>
            <Route path="/dashboard" component={Dashboard} />
            <Route path="/platforms" component={Platforms} />
            <Route path="/coach" component={Coach} />
            <Route path="/recommendations" component={Recommendations} />
            <Route path="/reflections" component={Reflections} />
            <Route path="/contests" component={Contests} />
            <Route path="/knowledge" component={Knowledge} />
            <Route component={NotFound} />
          </Switch>
        </AppShell>
      </Route>
    </Switch>
  );
}
