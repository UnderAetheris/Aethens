import { useAetherisState } from "./hooks/useAetherisState";
import { Composer } from "./components/Composer";
import { QueueList } from "./components/QueueList";
import { ActivityLog } from "./components/ActivityLog";
import { Indicators } from "./components/Indicators";
import { Skeletons } from "./components/Skeletons";
import { ConnectionBanner } from "./components/ConnectionBanner";
import { TaskDetail } from "./components/TaskDetail";

export default function App() {
  const { snap, status, submit } = useAetherisState();

  if (!snap) {
    return <Skeletons />;
  }

  const selected = snap.tasks[0] ?? null;

  return (
    <div className="app-shell">
      <ConnectionBanner status={status} />
      <header className="app-header">
        <div>
          <h1>Aetheris</h1>
          <p>Real backend integration, thin UI client.</p>
        </div>
        <Composer onSubmit={submit} />
      </header>
      <main className="app-grid">
        <section className="panel">
          <Indicators summary={snap.evalSummary} knowledge={snap.knowledge} learning={snap.learning} />
        </section>
        <section className="panel">
          <QueueList tasks={snap.tasks} selected={selected} />
        </section>
        <section className="panel">
          <TaskDetail task={selected} />
        </section>
        <section className="panel wide">
          <ActivityLog events={snap.events} />
        </section>
      </main>
    </div>
  );
}
