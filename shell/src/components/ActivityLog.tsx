import type { EventOut } from "../api/client";

interface ActivityLogProps {
  events: EventOut[];
}

export function ActivityLog({ events }: ActivityLogProps) {
  return (
    <div className="activity-log">
      <h2>Activity</h2>
      <ul>
        {events.map((event, index) => (
          <li key={`${event.kind}-${index}`}>
            <strong>{event.kind}</strong>: {JSON.stringify(event.data)}
          </li>
        ))}
      </ul>
    </div>
  );
}
