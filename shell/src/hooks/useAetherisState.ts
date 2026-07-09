import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type EvalSummaryOut, type EventOut, type KnowledgeOut, type LearningStateOut, type TaskOut } from "../api/client";

export interface Snapshot {
  tasks: TaskOut[];
  events: EventOut[];
  evalSummary: EvalSummaryOut | null;
  knowledge: KnowledgeOut[];
  learning: LearningStateOut | null;
}

export type ConnStatus = "connecting" | "live" | "reconnecting";

const BASE_INTERVAL = 1000;
const BACKOFF = [1000, 2000, 5000];

export function useAetherisState() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const fails = useRef(0);
  const timer = useRef<number | null>(null);
  const optimistic = useRef<TaskOut[]>([]);
  const snapRef = useRef<Snapshot | null>(null);

  const schedule = useCallback((ms: number) => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
    }
    timer.current = window.setTimeout(() => void poll(), ms);
  }, []);

  const poll = useCallback(async () => {
    try {
      const [tasks, events, evalSummary, knowledge, learning] = await Promise.all([
        api.listTasks(),
        api.recentEvents(),
        api.evalSummary(),
        api.knowledge(),
        api.learningState(),
      ]);
      const known = new Set(tasks.map((task) => task.id));
      optimistic.current = optimistic.current.filter((item) => !known.has(item.id));
      const merged = [...optimistic.current, ...tasks];
      const nextSnap = { tasks: merged, events, evalSummary, knowledge, learning };
      snapRef.current = nextSnap;
      setSnap(nextSnap);
      fails.current = 0;
      setStatus("live");
      schedule(BASE_INTERVAL);
    } catch {
      fails.current += 1;
      setStatus(snapRef.current ? "reconnecting" : "connecting");
      const delay = BACKOFF[Math.min(fails.current - 1, BACKOFF.length - 1)];
      schedule(delay);
    }
  }, [schedule]);

  useEffect(() => {
    snapRef.current = snap;
  }, [snap]);

  useEffect(() => {
    void poll();
    return () => {
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
      }
    };
  }, [poll]);

  const submit = useCallback(async (task: string, priority = 0) => {
    const temp: TaskOut = {
      id: `optimistic-${Date.now()}`,
      task,
      state: "queued",
      detail: "",
      priority,
      created_at: Date.now() / 1000,
      updated_at: Date.now() / 1000,
    };
    optimistic.current = [temp, ...optimistic.current];
    setSnap((current) => (current ? { ...current, tasks: [temp, ...current.tasks] } : current));
    try {
      await api.submitTask(task, priority);
      await poll();
    } catch (error) {
      optimistic.current = optimistic.current.filter((item) => item.id !== temp.id);
      setSnap((current) => (current ? { ...current, tasks: current.tasks.filter((item) => item.id !== temp.id) } : current));
      throw error as ApiError;
    }
  }, [poll]);

  return { snap, status, submit };
}
