import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { apiGet, ApiError } from "@/lib/api";

/** Backend gate record (loose) */
type GateApi = {
  id: number;
  baseline_run_id?: number;
  candidate_run_id?: number;
  status?: string; // pass/fail/etc
  created_at?: string;
  details_json?: any;
};

type GatesResponse = GateApi[] | { items: GateApi[] };

/** UI row */
type GateRow = {
  id: number;
  baselineRunId: number | "—";
  candidateRunId: number | "—";
  status: "SHIP" | "BLOCK" | "PENDING" | "PASS" | "FAIL" | "—";
  createdAt: string;
};

function pillGate(s: GateRow["status"]) {
  if (s === "SHIP" || s === "PASS") return "bg-emerald-600/20 text-emerald-200";
  if (s === "BLOCK" || s === "FAIL") return "bg-red-600/20 text-red-200";
  if (s === "PENDING") return "bg-amber-600/20 text-amber-200";
  return "bg-slate-600/20 text-slate-200";
}

function normalizeGateStatus(s?: string): GateRow["status"] {
  const v = (s ?? "").trim().toLowerCase();

  // DB style
  if (v === "pass") return "PASS";
  if (v === "fail") return "FAIL";

  // ship/ci style (if you ever reuse this table)
  if (v.includes("ship")) return "SHIP";
  if (v.includes("block")) return "BLOCK";
  if (v.includes("pending") || v.includes("running")) return "PENDING";

  return "—";
}

function formatDate(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

async function fetchGates(signal?: AbortSignal): Promise<GateApi[]> {
  // Keep both candidates; works whether apiGet prefixes /api or not.
  const candidates = ["/api/gates", "/gates"];

  let lastErr: unknown = null;
  for (const path of candidates) {
    try {
      const res = await apiGet<GatesResponse>(path, signal);

      if (Array.isArray(res)) return res;

      if (res && typeof res === "object" && Array.isArray((res as any).items)) {
        return (res as any).items as GateApi[];
      }

      // if a single object ever comes back
      if (res && typeof res === "object" && (res as any).id != null) {
        return [res as any as GateApi];
      }

      return [];
    } catch (e) {
      lastErr = e;
    }
  }

  throw lastErr;
}

function mapGateToRow(g: GateApi): GateRow {
  return {
    id: g.id,
    baselineRunId: g.baseline_run_id ?? "—",
    candidateRunId: g.candidate_run_id ?? "—",
    status: normalizeGateStatus(g.status),
    createdAt: formatDate(g.created_at),
  };
}

export function Gates() {
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<GateRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // initial load + polling
  useEffect(() => {
    let alive = true;
    const ac = new AbortController();

    async function loadOnce() {
      try {
        setError(null);
        const gates = await fetchGates(ac.signal);
        if (!alive) return;

        const mapped = gates.map(mapGateToRow).sort((a, b) => b.id - a.id);
        setRows(mapped);
      } catch (e: any) {
        if (!alive) return;
        if (e?.name === "AbortError") return;

        if (e instanceof ApiError) setError(`${e.message} (HTTP ${e.status})`);
        else setError("Failed to load gates.");
      } finally {
        if (alive) setLoading(false);
      }
    }

    setLoading(true);
    loadOnce();

    // polling every 5s (silent)
    const t = window.setInterval(() => {
      fetchGates(ac.signal)
        .then((gates) => {
          if (!alive) return;
          const mapped = gates.map(mapGateToRow).sort((a, b) => b.id - a.id);
          setRows(mapped);
        })
        .catch(() => {
          // ignore transient polling errors; keep last good table
        });
    }, 5000);

    return () => {
      alive = false;
      ac.abort();
      window.clearInterval(t);
    };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => {
      return (
        String(r.id).includes(q) ||
        String(r.baselineRunId).toLowerCase().includes(q) ||
        String(r.candidateRunId).toLowerCase().includes(q) ||
        r.status.toLowerCase().includes(q) ||
        r.createdAt.toLowerCase().includes(q)
      );
    });
  }, [query, rows]);

  return (
    <div className="space-y-4">
      <Card className="border-slate-800 bg-slate-950/40">
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <CardTitle className="text-sm text-slate-100">Gates</CardTitle>
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by run id / status..."
            className="max-w-xs border-slate-800 bg-slate-950/40 text-slate-100 placeholder:text-slate-500"
          />
        </CardHeader>

        <CardContent className="space-y-3">
          {loading ? (
            <div className="text-sm text-slate-400">Loading gate evaluations…</div>
          ) : error ? (
            <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-3 text-sm text-red-200">
              {error}
              <div className="mt-1 text-xs text-red-300/80">
                Expected backend JSON endpoint: <code>/api/gates</code> (or{" "}
                <code>/gates</code>).
                <br />
                If you still see <code>/ui/gates</code> in the error, your browser
                is serving an old build — hard refresh.
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-800 overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="border-slate-800">
                    <TableHead className="text-slate-300">Gate</TableHead>
                    <TableHead className="text-slate-300">Baseline run</TableHead>
                    <TableHead className="text-slate-300">Candidate run</TableHead>
                    <TableHead className="text-slate-300">Decision</TableHead>
                    <TableHead className="text-slate-300">Created</TableHead>
                  </TableRow>
                </TableHeader>

                <TableBody>
                  {filtered.length === 0 ? (
                    <TableRow className="border-slate-800">
                      <TableCell colSpan={5} className="text-slate-400">
                        No gate evaluations found.
                      </TableCell>
                    </TableRow>
                  ) : (
                    filtered.map((g) => {
                      const baselineId =
                        g.baselineRunId === "—" ? null : Number(g.baselineRunId);
                      const candidateId =
                        g.candidateRunId === "—" ? null : Number(g.candidateRunId);

                      return (
                        <TableRow
                          key={g.id}
                          className="border-slate-800 cursor-pointer hover:bg-slate-900/50"
                          // ✅ Row click goes to Gate detail
                          onClick={() => navigate(`/gates/${g.id}`)}
                        >
                          <TableCell className="text-slate-100 font-medium">
                            <Link
                              to={`/gates/${g.id}`}
                              className="hover:underline"
                              onClick={(e) => e.stopPropagation()}
                            >
                              #{g.id}
                            </Link>
                          </TableCell>

                          <TableCell className="text-slate-200">
                            {baselineId == null ? (
                              "—"
                            ) : (
                              <Link
                                to={`/runs/${baselineId}`}
                                className="hover:underline"
                                onClick={(e) => e.stopPropagation()}
                              >
                                #{baselineId}
                              </Link>
                            )}
                          </TableCell>

                          <TableCell className="text-slate-200">
                            {candidateId == null ? (
                              "—"
                            ) : (
                              <Link
                                to={`/runs/${candidateId}`}
                                className="hover:underline"
                                onClick={(e) => e.stopPropagation()}
                              >
                                #{candidateId}
                              </Link>
                            )}
                          </TableCell>

                          <TableCell>
                            <Badge className={pillGate(g.status)}>{g.status}</Badge>
                          </TableCell>

                          <TableCell className="text-slate-400">{g.createdAt}</TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
