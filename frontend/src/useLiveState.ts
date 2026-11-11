import { useCallback, useEffect, useRef, useState } from "react";
import type { ActionData, AppState } from "./types";
export function useLiveState() {
  const [state, setState] = useState<AppState | null>(null);
  const [connection, setConnection] = useState<
    "connecting" | "connected" | "reconnecting"
  >("connecting");
  const [error, setError] = useState("");
  const token = useRef(""),
    latest = useRef<AppState | null>(null);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("desktop_loading"))
      return;
    const controller = new AbortController();
    let alive = true;
    const update = (s: AppState) => {
      latest.current = s;
      setState(s);
    };
    async function connect() {
      while (alive) {
        try {
          const session = await fetch("/api/session", {
            signal: controller.signal,
            cache: "no-store",
          });
          if (!session.ok) throw Error("Панель пока недоступна");
          const data = await session.json();
          token.current = data.token;
          update(data.state);
          setError("");
          const response = await fetch("/api/events", {
            headers: { "X-Token": token.current },
            signal: controller.signal,
          });
          if (!response.ok || !response.body)
            throw Error("Нет связи с панелью");
          setConnection("connected");
          const reader = response.body.getReader(),
            decoder = new TextDecoder();
          let buffer = "";
          while (alive) {
            const part = await reader.read();
            if (part.done) break;
            buffer += decoder.decode(part.value, { stream: true });
            let end;
            while ((end = buffer.indexOf("\n\n")) !== -1) {
              const frame = buffer.slice(0, end);
              buffer = buffer.slice(end + 2);
              const line = frame
                .split("\n")
                .find((x) => x.startsWith("data: "));
              if (line) {
                update(JSON.parse(line.slice(6)));
                setConnection("connected");
              }
            }
          }
        } catch (e) {
          if (controller.signal.aborted) return;
          if (!latest.current)
            setError(
              e instanceof Error ? e.message : "Не удалось подключиться",
            );
        }
        if (alive) {
          setConnection("reconnecting");
          await new Promise((resolve) => setTimeout(resolve, 1800));
        }
      }
    }
    void connect();
    return () => {
      alive = false;
      controller.abort();
    };
  }, []);
  const request = useCallback(
    async (path: string, options: RequestInit = {}) => {
      const response = await fetch(path, {
        ...options,
        headers: {
          "X-Token": token.current,
          "Content-Type": "application/json",
          ...options.headers,
        },
      });
      const value = await response.json();
      if (!response.ok) {
        const detail = value.detail;
        throw Error(
          typeof detail === "string"
            ? detail
            : value.error || "Проверьте введённые данные и попробуйте снова",
        );
      }
      return value;
    },
    [],
  );
  const action = useCallback(
    (data: ActionData) =>
      request("/api/action", {
        method: "POST",
        body: JSON.stringify({ ...data, prompt_id: latest.current?.prompt_id }),
      }),
    [request],
  );
  return { state, connection, error, setError, action, request };
}
