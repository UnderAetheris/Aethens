import type { TaskOut } from "../api/client";

interface QueueListProps {
  tasks: TaskOut[];
  selected: TaskOut | null;
}

export function QueueList({ tasks, selected }: QueueListProps) {
  return (
    <div className="queue-list">
      <h2>Queue</h2>
      {tasks.map((task) => (
        <div key={task.id} className={`task-row ${selected?.id === task.id ? "selected" : ""}`}>
          <strong>{task.task}</strong>
          <span>{task.state}</span>
        </div>
      ))}
    </div>
  );
}
