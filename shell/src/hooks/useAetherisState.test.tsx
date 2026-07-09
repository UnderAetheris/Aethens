import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { useAetherisState } from "./useAetherisState";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      listTasks: vi.fn(),
      recentEvents: vi.fn(),
      evalSummary: vi.fn(),
      knowledge: vi.fn(),
      learningState: vi.fn(),
      submitTask: vi.fn(),
    },
  };
});

beforeEach(() => {
  vi.mocked(api.listTasks).mockResolvedValue([]);
  vi.mocked(api.recentEvents).mockResolvedValue([]);
  vi.mocked(api.evalSummary).mockResolvedValue({ passed: 4, total: 5, pass_rate: 0.8, ts: 0, available: true });
  vi.mocked(api.knowledge).mockResolvedValue([]);
  vi.mocked(api.learningState).mockResolvedValue({ extra_keywords: {}, steps: [] });
  vi.mocked(api.submitTask).mockResolvedValue({ id: "task-1", task: "hi", state: "queued", detail: "", priority: 0, created_at: 0, updated_at: 0 });
});

describe("useAetherisState", () => {
  it("becomes live after first poll", async () => {
    const { result } = renderHook(() => useAetherisState());
    await waitFor(() => expect(result.current.status).toBe("live"));
    expect(result.current.snap?.evalSummary?.pass_rate).toBe(0.8);
  });

  it("optimistically shows a submitted task", async () => {
    const { result } = renderHook(() => useAetherisState());
    await waitFor(() => expect(result.current.status).toBe("live"));
    await act(async () => {
      await result.current.submit("hi");
    });
    await waitFor(() => expect(result.current.snap?.tasks.some((task) => task.task === "hi")).toBe(true));
  });
});
