import { useState } from "react";

interface ComposerProps {
  onSubmit: (task: string, priority?: number) => Promise<unknown>;
}

export function Composer({ onSubmit }: ComposerProps) {
  const [task, setTask] = useState("");
  const [priority, setPriority] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!task.trim()) {
      return;
    }
    try {
      setError(null);
      await onSubmit(task.trim(), priority);
      setTask("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to submit task");
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <input value={task} onChange={(event) => setTask(event.target.value)} placeholder="Describe the next task" />
      <input type="number" value={priority} onChange={(event) => setPriority(Number(event.target.value))} />
      <button type="submit">Submit</button>
      {error ? <span className="error">{error}</span> : null}
    </form>
  );
}
