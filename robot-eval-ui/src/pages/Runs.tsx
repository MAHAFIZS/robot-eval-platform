import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { apiGet, ApiError } from "@/lib/api";

/** UI types */
type RunStatus = "queued" | "running" | "completed" | "failed" | "unknown";
type GateStatus = "SHIP" | "BLOCK" | "PENDING" | "—";


type RunRow = {
  id: number;
  model: string;
  suite: string;
  dataset: string;
  backend: string;
  status: RunStatus;
  gate: GateStatus;
  createdAt: string;
  reportUrl?: string | null;
  videoUrl?: string | null;
};

/** Backend types */
type RunApi = {
  id: number;
  model_id?: number | string;
  model_name?: string;
  suite_id?: number | string;
  suite_name?: string;
  dataset_id?: number | string;
  dataset_name?: string;
  backend?: string;
  status?: string;
  created_at?: string;
  label?: string | null;
  notes?: string | null;
  gate_status?: "pass" | "fail" | null;
  gate_id?: number | null;
  gate_link?: string | null;
  // ✅ if backend provides them, we use them
  report_uri?: string | null;
  rollout_uri?: string | null;

  // optional (some builds use these names)
  report_url?: string | null;
  rollout_url?: string | null;
};

type RunsResponse = RunApi[] | { items?: RunApi[]; value?: RunApi[] };


/** Helpers */
function pillStatus(status: RunStatus) {
  if (status === "completed") return "bg-emerald-600/20 text-emerald-200";
  if (status === "running") return "bg-sky-600/20 text-sky-200";
  if (status === "queued") return "bg-amber-600/20 text-amber-200";
  if (status === "failed") return "bg-red-600/20 text-red-200";
  return "bg-slate-600/20 text-slate-200";
}

function pillGate(gate: GateStatus) {
  if (gate === "pass") return "bg-emerald-600/20 text-emerald-200";
  if (gate === "fail") return "bg-red-600/20 text-red-200";
  return "bg-slate-600/20 text-slate-200";
}

function normalizeGate(g?: string | null): GateStatus {
  const v = (g || "").toLowerCase();
  if (v === "pass") return "SHIP";
  if (v === "fail") return "BLOCK";
  return "PENDING"; // or "—" if you prefer
}

function normalizeStatus(s?: string): RunStatus {
  const v = (s || "").toLowerCase();
  if (v.includes("queue")) return "queued";
  if (v.includes("run")) return "running";
  if (v.includes("complete") || v.includes("done") || v === "success") return "completed";
  if (v.includes("fail") || v.includes("error")) return "failed";
  return "unknown";
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

/** You can later wire real gate status per run; for now keep — */


/** Build artifact URLs.
 * Priority:
 * 1) explicit API fields (report_uri/rollout_uri or report_url/rollout_url)
 * 2) fallback to local artifact convention: /artifacts/<id>/report.html and /artifacts/<id>/rollout.mp4
 */
function getReportUrl(r: RunApi): string | null {
  // Always go through backend resolver (handles s3://, file://, local artifacts)
  return `/api/runs/${r.id}/report`;
}

function getVideoUrl(r: RunApi): string | null {
  // Always go through backend resolver (your backend serves /api/runs/:id/rollout)
  return `/api/runs/${r.id}/rollout`;
}


function mapRunToRow(r: RunApi): RunRow {
  const model =
    r.label?.trim() ||
    r.model_name ||
    (r.model_id != null ? `model-${r.model_id}` : "—");

  const suite = r.suite_name || (r.suite_id != null ? `suite-${r.suite_id}` : "—");
  const dataset = r.dataset_name || (r.dataset_id != null ? `dataset-${r.dataset_id}` : "—");

  return {
    id: r.id,
    model,
    suite,
    dataset,
    backend: r.backend || "—",
    status: normalizeStatus(r.status),
    gate: normalizeGate((r as any).gate_status), // ✅ HERE
    createdAt: formatDate(r.created_at),
    reportUrl: getReportUrl(r),
    videoUrl: getVideoUrl(r),
  };
}


async function fetchRuns(signal?: AbortSignal): Promise<RunApi[]> {
  const res = await apiGet<RunsResponse>("/api/runs?limit=50", signal);

  if (Array.isArray(res)) return res;

  if (res && typeof res === "object") {
    const anyRes = res as any;
    if (Array.isArray(anyRes.items)) return anyRes.items as RunApi[];
    if (Array.isArray(anyRes.value)) return anyRes.value as RunApi[];
  }

  return [];
}


function IconLink({
  href,
  label,
  title,
}: {
  href: string | null | undefined;
  label: string;
  title: string;
}) {
  if (!href) {
    return (
      <span className="opacity-30 select-none" title={`${title} (not available)`}>
        {label}
      </span>
    );
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="hover:opacity-80"
      title={title} // ✅ simple tooltip
      onClick={(e) => e.stopPropagation()}
    >
      {label}
    </a>
  );
}

export function Runs() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<RunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setError(null);

    fetchRuns(ac.signal)
      .then((runs) => {
        const mapped = runs.map(mapRunToRow).sort((a, b) => b.id - a.id);
        setRows(mapped);
      })
      .catch((e) => {
        if (e?.name === "AbortError") return;
        if (e instanceof ApiError) setError(`${e.message} (HTTP ${e.status})`);
        else setError("Failed to load runs.");
      })
      .finally(() => setLoading(false));

    return () => ac.abort();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => {
      return (
        String(r.id).includes(q) ||
        r.model.toLowerCase().includes(q) ||
        r.suite.toLowerCase().includes(q) ||
        r.dataset.toLowerCase().includes(q) ||
        r.backend.toLowerCase().includes(q) ||
        r.status.toLowerCase().includes(q) ||
        r.gate.toLowerCase().includes(q)
      );
    });
  }, [query, rows]);

  return (
    <div className="space-y-4">
      <Card className="border-slate-800 bg-slate-950/40">
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <CardTitle className="text-sm text-slate-100">Runs</CardTitle>

          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by model/suite/dataset..."
            className="max-w-xs border-slate-800 bg-slate-950/40 text-slate-100 placeholder:text-slate-500"
          />
        </CardHeader>

        <CardContent className="space-y-3">
          {loading ? (
            <div className="text-sm text-slate-400">Loading runs…</div>
          ) : error ? (
            <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-3 text-sm text-red-200">
              {error}
              <div className="mt-1 text-xs text-red-300/80">
                Tip: backend must serve <code className="mx-1">/api/runs</code> and ideally
                <code className="mx-1">/artifacts/&lt;id&gt;/...</code>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-slate-800 overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="border-slate-800">
                    <TableHead className="text-slate-300">Run</TableHead>
                    <TableHead className="text-slate-300">Model</TableHead>
                    <TableHead className="text-slate-300">Suite</TableHead>
                    <TableHead className="text-slate-300">Dataset</TableHead>
                    <TableHead className="text-slate-300">Backend</TableHead>
                    <TableHead className="text-slate-300">Status</TableHead>
                    <TableHead className="text-slate-300">Gate</TableHead>
                    <TableHead className="text-slate-300">Media</TableHead>
                    <TableHead className="text-slate-300">Created</TableHead>
                  </TableRow>
                </TableHeader>

                <TableBody>
                  {filtered.length === 0 ? (
                    <TableRow className="border-slate-800">
                      <TableCell colSpan={9} className="text-slate-400">
                        No runs found.
                      </TableCell>
                    </TableRow>
                  ) : (
                    filtered.map((r) => (
                      <TableRow key={r.id} className="border-slate-800">
                        <TableCell className="text-slate-100 font-medium">
                          <Link className="hover:underline" to={`/runs/${r.id}`}>
                            #{r.id}
                          </Link>
                        </TableCell>

                        <TableCell className="text-slate-200">{r.model}</TableCell>
                        <TableCell className="text-slate-200">{r.suite}</TableCell>
                        <TableCell className="text-slate-200">{r.dataset}</TableCell>
                        <TableCell className="text-slate-200">{r.backend}</TableCell>

                        <TableCell>
                          <Badge className={pillStatus(r.status)}>{r.status}</Badge>
                        </TableCell>

                        <TableCell>
                          <Badge className={pillGate(r.gate)}>{r.gate}</Badge>
                        </TableCell>

                        <TableCell className="text-slate-200">
                          <div className="flex items-center gap-3">
                            <IconLink
                              href={r.reportUrl}
                              label="📄"
                              title="Open evaluation report"
                            />
                            <IconLink
                              href={r.videoUrl}
                              label="🎥"
                              title="Open rollout video"
                            />
                          </div>
                        </TableCell>

                        <TableCell className="text-slate-400">{r.createdAt}</TableCell>
                      </TableRow>
                    ))
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
