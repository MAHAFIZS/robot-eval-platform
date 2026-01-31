import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiGet, ApiError, apiUrl } from "@/lib/api";

type RunApi = {
  id: number;
  status?: string;
  created_at?: string;
  started_at?: string;
  ended_at?: string;
  backend?: string;
  model_name?: string;
  model_id?: number | string;
  suite_name?: string;
  suite_id?: number | string;
  dataset_name?: string;
  dataset_id?: number | string;

  // Stored URIs are fine to DISPLAY, but NOT to use as <a href> when they are s3://
  report_uri?: string | null;
  rollout_uri?: string | null;

  // Optional but recommended for failures
  error_message?: string | null;

  summary_json?: any;
  [k: string]: any;
};

function fmt(iso?: string) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function statusPill(status?: string) {
  const v = (status || "").toLowerCase();
  if (v.includes("complete") || v.includes("done") || v.includes("success"))
    return "bg-emerald-600/20 text-emerald-200";
  if (v.includes("run"))
    return "bg-sky-600/20 text-sky-200";
  if (v.includes("queue"))
    return "bg-amber-600/20 text-amber-200";
  if (v.includes("fail") || v.includes("error"))
    return "bg-red-600/20 text-red-200";
  return "bg-slate-700/30 text-slate-200";
}

export function RunDetail() {
  const { id } = useParams();
  const runId = useMemo(() => Number(id), [id]);

  const [run, setRun] = useState<RunApi | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ✅ IMPORTANT: always use backend redirect endpoints, never s3://
  const reportHref = Number.isFinite(runId) ? apiUrl(`/api/runs/${runId}/report`) : "#";
  const videoHref = Number.isFinite(runId) ? apiUrl(`/api/runs/${runId}/rollout`) : "#";

  const load = () => {
    if (!id || !Number.isFinite(runId)) return;

    const ac = new AbortController();
    setLoading(true);
    setError(null);

    apiGet<RunApi>(`/api/runs/${runId}`, ac.signal)
      .then((data) => setRun(data))
      .catch((e) => {
        if (e?.name === "AbortError") return;
        if (e instanceof ApiError) setError(`${e.message} (HTTP ${e.status})`);
        else setError("Failed to load run detail.");
      })
      .finally(() => setLoading(false));

    return () => ac.abort();
  };

  useEffect(() => {
    const cleanup = load();
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  return (
    <div className="space-y-4">
      <div className="text-sm text-slate-400">
        <Link className="hover:underline" to="/runs">
          ← Back to Runs
        </Link>
      </div>

      <Card className="border-slate-800 bg-slate-950/40">
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <CardTitle className="text-sm text-slate-100">Run #{id}</CardTitle>

          <div className="flex items-center gap-2">
            <a
              href={reportHref}
              target="_blank"
              rel="noreferrer"
              title="Open evaluation report"
              className="rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1 text-xs text-slate-200 hover:bg-slate-900/50"
            >
              📄 Report
            </a>

            <a
              href={videoHref}
              target="_blank"
              rel="noreferrer"
              title="Open rollout video"
              className="rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1 text-xs text-slate-200 hover:bg-slate-900/50"
            >
              🎥 Video
            </a>
          </div>
        </CardHeader>

        <CardContent className="space-y-3 text-sm text-slate-300">
          {loading ? (
            "Loading…"
          ) : error ? (
            <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-3 text-sm text-red-200">
              {error}
            </div>
          ) : !run ? (
            "No data."
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                <Badge className={statusPill(run.status)}>
                  status: {run.status ?? "—"}
                </Badge>
                <Badge className="bg-slate-700/30 text-slate-200">
                  backend: {run.backend ?? "—"}
                </Badge>
                <Badge className="bg-slate-700/30 text-slate-200">
                  model:{" "}
                  {run.model_name ??
                    (run.model_id != null ? `model-${run.model_id}` : "—")}
                </Badge>
              </div>

              {/* ✅ Failure reason (if run failed) */}
              {String(run.status || "").toLowerCase().includes("fail") && (
                <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-3">
                  <div className="font-semibold text-red-200">Failure reason</div>
                  <div className="mt-1 text-sm text-red-100 whitespace-pre-wrap break-words">
                    {run.error_message || "No error_message provided by backend yet."}
                  </div>
                </div>
              )}

              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-800 bg-slate-950/30 p-3">
                  <div className="text-xs text-slate-400">Created</div>
                  <div className="text-sm text-slate-200">{fmt(run.created_at)}</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-950/30 p-3">
                  <div className="text-xs text-slate-400">Started / Ended</div>
                  <div className="text-sm text-slate-200">
                    {fmt(run.started_at)} → {fmt(run.ended_at)}
                  </div>
                </div>
              </div>

              {/* Inline preview */}
              <div className="rounded-xl border border-slate-800 bg-slate-950/30 p-3">
                <div className="mb-2 text-xs text-slate-400">Rollout preview</div>
                <video
                  controls
                  preload="metadata"
                  className="w-full rounded-lg border border-slate-800"
                  src={videoHref}
                />
              </div>

              {/* Optional: show stored URIs for debugging */}
              <div className="rounded-lg border border-slate-800 bg-slate-950/30 p-3 text-xs text-slate-400">
                <div>Stored report_uri: {run.report_uri ?? "—"}</div>
                <div>Stored rollout_uri: {run.rollout_uri ?? "—"}</div>
              </div>

              <pre className="whitespace-pre-wrap break-words rounded-lg border border-slate-800 bg-slate-950/30 p-3 text-xs text-slate-200">
                {JSON.stringify(run, null, 2)}
              </pre>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
