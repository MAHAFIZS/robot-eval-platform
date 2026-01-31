import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiGet, apiUrl } from "@/lib/api";

type GateApi = any;

function gateClass(status?: string) {
  const v = (status || "").toUpperCase();
  if (v.includes("PASS") || v.includes("SHIP")) return "bg-emerald-600/20 text-emerald-200";
  if (v.includes("FAIL") || v.includes("BLOCK")) return "bg-red-600/20 text-red-200";
  if (v.includes("PENDING")) return "bg-amber-600/20 text-amber-200";
  return "bg-slate-600/20 text-slate-200";
}

export function GateDetail() {
  const { id } = useParams();
  const [gate, setGate] = useState<GateApi | null>(null);
  const [openJson, setOpenJson] = useState(false);

  useEffect(() => {
    if (!id) return;
    const ac = new AbortController();

    apiGet<GateApi>(`/api/gates/${id}`, ac.signal).then(setGate);

    return () => ac.abort();
  }, [id]);

  const baseline = gate?.baseline_run_id as number | undefined;
  const candidate = gate?.candidate_run_id as number | undefined;

  // ✅ IMPORTANT: never open s3://... in browser
  // Always go through backend endpoints that redirect to MinIO presigned URLs.
  const candidateReportUrl = candidate ? apiUrl(`/api/runs/${candidate}/report`) : null;
  const baselineReportUrl = baseline ? apiUrl(`/api/runs/${baseline}/report`) : null;

  return (
    <div className="space-y-4">
      <div className="text-sm text-slate-400">
        <Link className="hover:underline" to="/gates">← Back to Gates</Link>
      </div>

      <Card className="border-slate-800 bg-slate-950/40">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm text-slate-100">Gate #{id}</CardTitle>
          <Badge className={gateClass(gate?.status)}>{gate?.status ?? "—"}</Badge>
        </CardHeader>

        <CardContent className="space-y-3 text-sm text-slate-300">
          <div className="flex flex-wrap gap-3">
            <Link className="hover:underline text-slate-200" to={baseline ? `/runs/${baseline}` : "#"}>
              Baseline: {baseline ? `#${baseline}` : "—"}
            </Link>
            <Link className="hover:underline text-slate-200" to={candidate ? `/runs/${candidate}` : "#"}>
              Candidate: {candidate ? `#${candidate}` : "—"}
            </Link>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-950/30 p-3">
            <div className="font-semibold text-slate-200">Decision</div>
            <div className="text-slate-300">
              {gate?.status ? `${gate.status} — based on gate evaluation.` : "—"}
            </div>
          </div>

          {/* ✅ PASTE YOUR REPORT LINKS BOX HERE (after Decision is perfect) */}
          <div className="rounded-lg border border-slate-800 bg-slate-950/30 p-3 space-y-2">
            <div className="font-semibold text-slate-200">Reports</div>

            {candidateReportUrl ? (
              <a
                href={candidateReportUrl}
                target="_blank"
                rel="noreferrer"
                className="block text-sm text-sky-400 hover:underline"
              >
                📄 Open candidate run report
              </a>
            ) : (
              <div className="text-sm text-slate-500">Candidate report not available</div>
            )}

            {baselineReportUrl ? (
              <a
                href={baselineReportUrl}
                target="_blank"
                rel="noreferrer"
                className="block text-sm text-sky-400 hover:underline"
              >
                📄 Open baseline run report
              </a>
            ) : (
              <div className="text-sm text-slate-500">Baseline report not available</div>
            )}
          </div>

          <button
            className="text-xs text-slate-300 underline hover:text-slate-100"
            onClick={() => setOpenJson((v) => !v)}
          >
            {openJson ? "Hide raw JSON" : "Show raw JSON"}
          </button>

          {openJson && (
            <pre className="whitespace-pre-wrap break-words rounded-lg border border-slate-800 bg-slate-950/30 p-3 text-xs text-slate-200">
              {JSON.stringify(gate, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
