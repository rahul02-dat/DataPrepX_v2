import { useEffect, useState } from "react";

type HealthState = "idle" | "loading" | "ok" | "error";

const GATEWAY_URL = import.meta.env.VITE_GATEWAY_URL || "http://localhost:8080";

export default function App() {
  const [state, setState] = useState<HealthState>("idle");
  const [detail, setDetail] = useState<string>("");

  const pingGateway = async () => {
    setState("loading");
    try {
      const res = await fetch(`${GATEWAY_URL}/healthz`);
      if (!res.ok) throw new Error(`status ${res.status}`);
      const body = await res.json();
      setDetail(JSON.stringify(body));
      setState("ok");
    } catch (err) {
      setDetail(err instanceof Error ? err.message : "unknown error");
      setState("error");
    }
  };

  useEffect(() => {
    pingGateway();
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>DataPrepX v2</h1>
      <p>Phase 0 scaffold — gateway health check.</p>
      <p>
        Gateway URL: <code>{GATEWAY_URL}</code>
      </p>
      <p>
        Status: <strong data-testid="health-status">{state}</strong>
      </p>
      {detail && <pre data-testid="health-detail">{detail}</pre>}
      <button onClick={pingGateway}>Re-check</button>
    </main>
  );
}
