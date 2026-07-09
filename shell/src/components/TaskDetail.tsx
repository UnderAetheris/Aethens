import type { TaskOut } from "../api/client";

interface TaskDetailProps {
  task: TaskOut | null;
}

export function TaskDetail({ task }: TaskDetailProps) {
  if (!task) {
    return <div className="task-detail">No task selected.</div>;
  }
  return (
    <div className="task-detail">
      <h2>Details</h2>
      <p>{task.task}</p>
      <p>Status: {task.state}</p>
      <p>Detail: {task.detail || "—"}</p>
    </div>
  );
}
