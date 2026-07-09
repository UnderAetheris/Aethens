import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./client";

afterEach(() => vi.restoreAllMocks());

describe("client", () => {
  it("parses a task list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify([{ id: "task-1", task: "hi", state: "queued", detail: "", priority: 0, created_at: 0, updated_at: 0 }]),
          { status: 200 }
        )
      )
    );
    const tasks = await api.listTasks();
    expect(tasks[0].state).toBe("queued");
  });

  it("submits a task with POST body", async () => {
    const spy = vi.fn(async () =>
      new Response(JSON.stringify({ id: "task-2", task: "go", state: "queued", detail: "", priority: 5, created_at: 0, updated_at: 0 }), { status: 201 })
    );
    vi.stubGlobal("fetch", spy);
    const task = await api.submitTask("go", 5);
    expect(task.priority).toBe(5);
    const call = spy.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit?] | undefined;
    const init = call?.[1];
    expect(init?.method).toBe("POST");
  });

  it("raises ApiError(http) with detail on 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "unknown task 'x'" }), { status: 404 }))
    );
    await expect(api.getTask("x")).rejects.toMatchObject({ kind: "http", status: 404 });
  });

  it("raises ApiError(network) when fetch throws", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("down"); }));
    await expect(api.listTasks()).rejects.toBeInstanceOf(ApiError);
  });
});
