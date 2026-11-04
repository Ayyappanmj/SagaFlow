import { useEffect, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, money, newKey, useApi } from "./api";

type Page = { items: any[]; total: number; limit: number; offset: number };
const PAGES = ["overview", "orders", "sagas", "inventory", "payments", "shipments", "failed", "dead-letters", "health"] as const;
const TITLES: Record<string, string> = { overview: "Overview", orders: "Orders & Failure Simulation", sagas: "Saga Explorer", inventory: "Inventory",
  payments: "Payments", shipments: "Shipments", failed: "Failed Workflows", "dead-letters": "Dead-Letter Messages", health: "System Health" };

const Badge = ({ s }: { s: string }) => <span className={`badge ${s}`}>{s}</span>;
const State = ({ loading, error, empty }: { loading: boolean; error: string | null; empty?: boolean }) =>
  loading ? <div className="empty" role="status">Loading…</div> : error ? <div className="err" role="alert">{error}</div> : empty ? <div className="empty">Nothing here yet.</div> : null;

function usePager(size = 10) { const [offset, setOffset] = useState(0); return { offset, size, setOffset }; }
const Pager = ({ p, total }: { p: ReturnType<typeof usePager>; total: number }) => (
  <div style={{ marginTop: 8 }}>
    <button className="secondary" disabled={p.offset === 0} onClick={() => p.setOffset(Math.max(0, p.offset - p.size))}>Prev</button>{" "}
    <button className="secondary" disabled={p.offset + p.size >= total} onClick={() => p.setOffset(p.offset + p.size)}>Next</button>{" "}
    <small>{total === 0 ? 0 : p.offset + 1}–{Math.min(total, p.offset + p.size)} of {total}</small>
  </div>);

function Overview() {
  const { data, error, loading } = useApi<any>("/stats", 5000);
  if (!data) return <State loading={loading} error={error} />;
  const s = data.sagas_by_state ?? {};
  const chart = Object.entries(s).map(([name, value]) => ({ name, value }));
  const m = (l: string, v: any) => <div className="card metric"><b>{v ?? "–"}</b><span>{l}</span></div>;
  return <>
    <State loading={false} error={error} />
    <div className="grid">{m("Total orders", data.total_orders)}{m("Completed", s.COMPLETED ?? 0)}{m("Failed", s.FAILED ?? 0)}
      {m("Compensated", s.COMPENSATED ?? 0)}{m("Requires attention", s.REQUIRES_ATTENTION ?? 0)}
      {m("Avg duration (s)", data.avg_workflow_seconds?.toFixed(2))}{m("Total retries", data.total_retries)}{m("Pending outbox", data.pending_outbox)}</div>
    <div className="card"><h3>Sagas by state</h3>
      {chart.length === 0 ? <div className="empty">No sagas yet</div> :
        <ResponsiveContainer width="100%" height={220}><BarChart data={chart}><XAxis dataKey="name" /><YAxis allowDecimals={false} /><Tooltip /><Bar dataKey="value" fill="#2f5bea" /></BarChart></ResponsiveContainer>}</div>
    <div className="card"><h3>Queue backlog</h3>{data.queue_backlog ? <table><tbody>{Object.entries(data.queue_backlog).map(([q, n]) => <tr key={q}><td>{q}</td><td>{String(n)}</td></tr>)}</tbody></table> : <div className="empty">Broker unavailable</div>}</div>
  </>;
}

const SCENARIOS: Record<string, any> = {
  "None (happy path)": {}, "Payment decline": { payment_decline: true }, "Shipping failure": { shipping_fail: true },
  "Inventory rejection": { inventory_reject: true }, "Payment timeouts (2, recoverable)": { payment_timeout: 2 },
  "Payment timeouts (exhaust retries)": { payment_timeout: 3 }, "Shipping failure + payment-void failure": { shipping_fail: true, compensation_fail: ["payment_void"] },
  "Duplicate message delivery": { duplicate_delivery: true }, "Reply lost after inventory commit": { drop_reply_once: ["inventory"] },
};
function Orders({ go }: { go: (sagaId: string) => void }) {
  const p = usePager(); const { data, error, loading, refetch } = useApi<Page>(`/orders?limit=${p.size}&offset=${p.offset}`, 5000);
  const [sku, setSku] = useState("WIDGET"); const [qty, setQty] = useState(2); const [price, setPrice] = useState(1000);
  const [cust, setCust] = useState("customer-1"); const [scn, setScn] = useState("None (happy path)"); const [msg, setMsg] = useState<string | null>(null);
  const valid = cust.trim() && sku.trim() && qty > 0 && qty <= 1000 && price >= 0;
  const submit = async () => {
    setMsg(null);
    try {
      const sim = SCENARIOS[scn];
      const r = await api<any>("/orders", { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": newKey() },
        body: JSON.stringify({ customer_ref: cust, items: [{ sku, quantity: qty, unit_price_cents: price }], simulate: Object.keys(sim).length ? sim : undefined }) });
      setMsg(`Order created. Saga ${r.saga_id}`); refetch(); go(r.saga_id);
    } catch (e: any) { setMsg(`Error: ${e.message}`); }
  };
  return <>
    <div className="card"><h3>Place an order (development)</h3>
      <label htmlFor="cust">Customer</label><input id="cust" value={cust} onChange={(e) => setCust(e.target.value)} />
      <label htmlFor="sku">SKU</label><input id="sku" value={sku} onChange={(e) => setSku(e.target.value)} />
      <label htmlFor="qty">Quantity</label><input id="qty" type="number" min={1} value={qty} onChange={(e) => setQty(+e.target.value)} />
      <label htmlFor="price">Unit price (cents)</label><input id="price" type="number" min={0} value={price} onChange={(e) => setPrice(+e.target.value)} />
      <label htmlFor="scn">Failure scenario (honoured only when the backend runs in dev mode)</label>
      <select id="scn" value={scn} onChange={(e) => setScn(e.target.value)}>{Object.keys(SCENARIOS).map((k) => <option key={k}>{k}</option>)}</select>
      <div style={{ marginTop: 12 }}><button disabled={!valid} onClick={submit}>Submit order</button> {msg && <span role="status">{msg}</span>}</div></div>
    <div className="card"><h3>Orders</h3><State loading={loading} error={error} empty={data?.items.length === 0} />
      {data && data.items.length > 0 && <><table><thead><tr><th>Order</th><th>Customer</th><th>Total</th><th>Status</th><th>Created</th></tr></thead><tbody>
        {data.items.map((o) => <tr key={o.id}><td><a href="#sagas" onClick={() => go(o.saga_id)}>{o.id.slice(0, 8)}</a></td><td>{o.customer_ref}</td><td>{money(o.total_cents)}</td><td><Badge s={o.status} /></td><td>{o.created_at}</td></tr>)}</tbody></table>
        <Pager p={p} total={data.total} /></>}</div></>;
}

function SagaDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const saga = useApi<any>(`/sagas/${id}`, 2000); const hist = useApi<{ items: any[] }>(`/sagas/${id}/history`, 2000);
  const [msg, setMsg] = useState<string | null>(null);
  const act = async (a: string, body?: any) => {
    try { await api(`/sagas/${id}/${a}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) }); setMsg(`${a} accepted`); saga.refetch(); hist.refetch(); }
    catch (e: any) { setMsg(`${a} rejected: ${e.message}`); }
  };
  const s = saga.data;
  return <div className="card"><button className="secondary" onClick={onClose}>Close</button>
    <State loading={saga.loading} error={saga.error} />
    {s && <><h3>Saga {s.id} <Badge s={s.state} /></h3>
      <p>Order {s.order_id} · step {s.current_step ?? "–"} · retries {s.retry_count} · version {s.version} · pending outbox {s.pending_outbox}</p>
      {s.error_code && <div className="err">{s.error_code}: {s.error_detail}</div>}
      <table><thead><tr><th>Step</th><th>Status</th><th>Attempts</th><th>Compensation</th><th>Last error</th></tr></thead><tbody>
        {s.steps.map((t: any) => <tr key={t.step_name}><td>{t.step_name}</td><td><Badge s={t.status} /></td><td>{t.attempts}/{t.max_attempts}</td><td><Badge s={t.compensation_status} /></td><td>{t.last_error ?? ""}</td></tr>)}</tbody></table>
      <p><button disabled={s.state !== "REQUIRES_ATTENTION"} onClick={() => act("retry", { clear_simulation: true })}>Retry (clear injected fault)</button>{" "}
        <button className="secondary" disabled={!["RUNNING", "COMPENSATING"].includes(s.state)} onClick={() => act("recover")}>Recover interrupted</button> {msg}</p></>}
    <h3>Execution timeline</h3><State loading={hist.loading} error={hist.error} />
    <div className="timeline">{hist.data?.items.map((e) => <div key={e.seq}><b>{e.event_type}</b> {e.step_name && `· ${e.step_name}`} {e.previous_state !== e.new_state && `· ${e.previous_state ?? "∅"} → ${e.new_state}`}
      <small>{e.created_at} · attempt {e.attempt} {e.compensation_status && `· compensation ${e.compensation_status}`} {e.error_detail && `· ${e.error_detail}`}</small></div>)}</div></div>;
}

function Sagas({ selected, setSelected, fixedState }: { selected: string | null; setSelected: (s: string | null) => void; fixedState?: string }) {
  const p = usePager(); const [state, setState] = useState(fixedState ?? ""); const [q, setQ] = useState("");
  const { data, error, loading } = useApi<Page>(`/sagas?limit=${p.size}&offset=${p.offset}${state ? `&state=${state}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`, 4000);
  return <>{selected && <SagaDetail id={selected} onClose={() => setSelected(null)} />}
    <div className="card"><label htmlFor="q">Search by saga ID or order ID</label><input id="q" value={q} onChange={(e) => { setQ(e.target.value.trim()); p.setOffset(0); }} />
      {!fixedState && <><label htmlFor="st">State</label><select id="st" value={state} onChange={(e) => { setState(e.target.value); p.setOffset(0); }}><option value="">All</option>
        {["RUNNING", "COMPLETED", "COMPENSATING", "COMPENSATED", "FAILED", "REQUIRES_ATTENTION"].map((x) => <option key={x}>{x}</option>)}</select></>}
      <State loading={loading} error={error} empty={data?.items.length === 0} />
      {data && data.items.length > 0 && <><table><thead><tr><th>Saga</th><th>Order</th><th>State</th><th>Step</th><th>Retries</th><th>Error</th><th>Updated</th></tr></thead><tbody>
        {data.items.map((s) => <tr key={s.id}><td><a href="#sagas" onClick={() => setSelected(s.id)}>{s.id.slice(0, 8)}</a></td><td>{s.order_id.slice(0, 8)}</td><td><Badge s={s.state} /></td><td>{s.current_step}</td><td>{s.retry_count}</td><td>{s.error_code}</td><td>{s.updated_at}</td></tr>)}</tbody></table>
        <Pager p={p} total={data.total} /></>}</div></>;
}

function Table({ path, cols }: { path: string; cols: string[] }) {
  const { data, error, loading } = useApi<{ items: any[] }>(path, 5000);
  return <div className="card"><State loading={loading} error={error} empty={data?.items.length === 0} />
    {data && data.items.length > 0 && <table><thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>
      {data.items.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{["status"].includes(c) ? <Badge s={r[c]} /> : String(r[c] ?? "")}</td>)}</tr>)}</tbody></table>}</div>;
}

function Health() {
  const { data, error, loading } = useApi<Record<string, any>>("/system-health", 5000);
  return <div className="card"><State loading={loading} error={error} />
    {data && <table><thead><tr><th>Service</th><th>Process</th><th>Ready</th><th>Dependency checks</th></tr></thead><tbody>
      {Object.entries(data).map(([n, v]) => <tr key={n}><td>{n}</td><td><Badge s={v.up ? "COMPLETED" : "FAILED"} /> {v.up ? "up" : "unreachable"}</td><td>{v.ready ? "yes" : "no"}</td><td>{v.checks ? Object.entries(v.checks).map(([k, ok]) => `${k}:${ok ? "ok" : "DOWN"}`).join("  ") : "–"}</td></tr>)}</tbody></table>}
    <p><small>Metrics: Prometheus http://localhost:9090 · Grafana http://localhost:3001</small></p></div>;
}

export default function App() {
  const [page, setPage] = useState<string>(location.hash.slice(1) || "overview"); const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { const f = () => setPage(location.hash.slice(1) || "overview"); addEventListener("hashchange", f); return () => removeEventListener("hashchange", f); }, []);
  const goSaga = (id: string) => { setSelected(id); location.hash = "sagas"; };
  return <div className="layout"><nav aria-label="Main"><h1>SagaFlow</h1>{PAGES.map((p) => <a key={p} href={`#${p}`} className={page === p ? "active" : ""}>{TITLES[p]}</a>)}</nav>
    <main><h2>{TITLES[page] ?? "Overview"}</h2>
      {page === "overview" && <Overview />}{page === "orders" && <Orders go={goSaga} />}
      {page === "sagas" && <Sagas selected={selected} setSelected={setSelected} />}
      {page === "inventory" && <Table path="/inventory" cols={["sku", "available", "reserved", "updated_at"]} />}
      {page === "payments" && <Table path="/payments" cols={["id", "order_id", "amount_cents", "status", "created_at"]} />}
      {page === "shipments" && <Table path="/shipments" cols={["id", "order_id", "tracking_number", "status", "created_at"]} />}
      {page === "failed" && <Sagas selected={selected} setSelected={setSelected} fixedState="REQUIRES_ATTENTION" />}
      {page === "dead-letters" && <Table path="/dead-letters" cols={["queue", "reason", "body"]} />}
      {page === "health" && <Health />}</main></div>;
}
