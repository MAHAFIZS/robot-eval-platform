import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  TrendingUp,
  XCircle,
  Hash,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiGet, ApiError } from "@/lib/api";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/* =========================
   Types
   ========================= */
type Decision = "SHIP" | "BLOCK" | "PENDING";

type ReleaseLatest = {
  suite_id: number;
  dataset_id: number;
  backend: string;
  baseline_run_id: number | null;
  decision: Decision;

  gate?: {
    gate_id: number;
    status: "pass" | "fail" | string;
    created_at?: string;
    candidate_run_id?: number;
    baseline_run_id?: number;
    details_json?: any;
  } | null;

  kpi?: Record<
    string,
    { baseline: number | null; candidate: number | null; delta: number | null }
  >;

  links?: {
    baseline_run?: string;
    candidate_run?: string;
    gate?: string;
    compare?: string;
  };

  baseline?: {
    id: number;
    status?: string;
    created_at?: string;
    summary_json?: any;
  } | null;

  candidate?: {
    id: number;
    status?: string;
    created_at?: string;
    summary_json?: any;
  } | null;
};

/* =========================
   Reusable KPI Card
   ========================= */
function Kpi({
  label,
  value,
  hint,
  icon,
  tooltip,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: ReactNode;
  tooltip?: string;
}) {
  const content = (
    <Card className="border-slate-800 bg-slate-950/40">
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium text-slate-300 flex items-center gap-2">
          {icon && <span className="opacity-90">{icon}</span>}
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold text-slate-100">{value}</div>
        {hint && <div className="mt-1 text-xs text-slate-400">{hint}</div>}
      </CardContent>
    </Card>
  );

  if (!tooltip) return content;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{content}</TooltipTrigger>
        <TooltipContent className="text-slate-100">{tooltip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/* =========================
   Helpers
   ========================= */
function fmtIso(iso?: string) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

function fmtPct(x: number | null | undefined) {
  if (x == null) return "—";
  return `${Math.round(x * 100)}%`;
}

function fmtNum(x: number | null | undefined, digits = 1) {
  if (x == null) return "—";
  const p = Math.pow(10, digits);
  return String(Math.round(x * p) / p);
}

function fmtDeltaPct(d: number | null | undefined) {
  if (d == null) return "";
  const sign = d > 0 ? "+" : "";
  return `Δ ${sign}${Math.round(d * 100)}% vs baseline`;
}

function fmtDeltaNum(d: number | null | undefined, unit = "", digits = 1) {
  if (d == null) return "";
  const sign = d > 0 ? "+" : "";
  return `Δ ${sign}${fmtNum(d, digits)}${unit} vs baseline`;
}

function normalizeDecision(d?: string | null): Decision {
  const v = (d || "").toUpperCase();
  if (v === "SHIP") return "SHIP";
  if (v === "BLOCK") return "BLOCK";
  return "PENDING";
}
function backendHref(pathOrUrl?: string | null) {
  if (!pathOrUrl) return null;
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;

  // backend URL (you can also move this to env later)
  const base = "http://localhost:8000";
  return `${base}${pathOrUrl.startsWith("/") ? "" : "/"}${pathOrUrl}`;
}

function decisionUi(shipStatus: Decision) {
  return {
    title:
      shipStatus === "SHIP"
        ? "SHIP — Safe to deploy"
        : shipStatus === "BLOCK"
        ? "BLOCK — Do not ship"
        : "PENDING — Waiting for results",
    subtitle:
      shipStatus === "SHIP"
        ? "Candidate passes all regression checks."
        : shipStatus === "BLOCK"
        ? "Candidate fails regression checks."
        : "No decision yet (run queued/running or no baseline lock).",
    leftBorder:
      shipStatus === "SHIP"
        ? "border-l-emerald-500"
        : shipStatus === "BLOCK"
        ? "border-l-red-500"
        : "border-l-amber-500",
    badgeClass:
      shipStatus === "SHIP"
        ? "bg-emerald-600/20 text-emerald-200"
        : shipStatus === "BLOCK"
        ? "bg-red-600/20 text-red-200"
        : "bg-amber-600/20 text-amber-200",
    icon:
      shipStatus === "SHIP" ? (
        <CheckCircle2 className="h-5 w-5 text-emerald-300" />
      ) : shipStatus === "BLOCK" ? (
        <XCircle className="h-5 w-5 text-red-300" />
      ) : (
        <AlertTriangle className="h-5 w-5 text-amber-300" />
      ),
  };
}

/* =========================
   Overview Page (LIVE)
   ========================= */
export function Overview() {
  // hardcode for now (later: read from settings UI)
  const suiteId = 1;
  const datasetId = 1;
  const backend = "mujoco";

  const [data, setData] = useState<ReleaseLatest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    setError(null);

    apiGet<ReleaseLatest>(
      `/api/releases/latest?suite_id=${suiteId}&dataset_id=${datasetId}&backend=${encodeURIComponent(
        backend
      )}`,
      ac.signal
    )
      .then((res) => setData(res))
      .catch((e) => {
        if (e?.name === "AbortError") return;
        if (e instanceof ApiError) setError(`${e.message} (HTTP ${e.status})`);
        else setError("Failed to load Overview data.");
      })
      .finally(() => setLoading(false));

    return () => ac.abort();
  }, [suiteId, datasetId, backend]);

  const shipStatus: Decision = normalizeDecision(data?.decision);
  const ui = decisionUi(shipStatus);

  // Why list: prefer backend reasons array
  const reasons: string[] =
    (Array.isArray(data?.gate?.details_json?.reasons)
      ? data?.gate?.details_json?.reasons
      : []) || [];

  // KPIs from response.kpi
  const kpi = data?.kpi || {};
  const kSuccess = kpi["success_rate"];
  const kDur = kpi["duration_mean_ms"];
  const kSafety = kpi["safety_violations"];
  const kTts = kpi["time_to_success_mean_s"] || kpi["time_to_success_mean"];
  const kEps = kpi["num_episodes"];

  const candidateId = data?.gate?.candidate_run_id ?? data?.candidate?.id ?? null;
  const baselineId = data?.baseline_run_id ?? data?.gate?.baseline_run_id ?? data?.baseline?.id ?? null;

  return (
    <div className="space-y-6">
      {/* ================= Gate Decision (Hero) ================= */}
      <Card className={`border-l-4 ${ui.leftBorder} border-slate-800 bg-slate-950/40`}>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div className="space-y-1">
            <CardTitle className="text-base font-semibold text-slate-100 flex items-center gap-2">
              {ui.icon}
              {ui.title}
            </CardTitle>
            <div className="text-sm text-slate-300">{ui.subtitle}</div>

            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-400">
              <span className="inline-flex items-center gap-1">
                <Hash className="h-3 w-3" />
                suite {suiteId} · dataset {datasetId} · {backend}
              </span>

              <span>Updated: {fmtIso(data?.gate?.created_at)}</span>

              {candidateId != null && (
                <Link className="text-slate-200 hover:underline" to={`/runs/${candidateId}`}>
                  Candidate #{candidateId}
                </Link>
              )}
              {baselineId != null && (
                <Link className="text-slate-200 hover:underline" to={`/runs/${baselineId}`}>
                  Baseline #{baselineId}
                </Link>
              )}

              {/* compare link from backend if you want */}
              {data?.links?.compare && (
                <a
                  href={backendHref(data.links.compare)}
                  className="text-slate-200 hover:underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  Compare
                </a>
              )}
              {data?.gate?.gate_id != null && (
                <Link className="text-slate-200 hover:underline" to={`/gates/${data.gate.gate_id}`}>
                  Gate #{data.gate.gate_id}
                </Link>
              )}
            </div>
          </div>

          <Badge className={ui.badgeClass}>{shipStatus}</Badge>
        </CardHeader>

        <CardContent className="space-y-2 text-sm text-slate-200">
          {loading ? (
            <div className="text-slate-400">Loading latest decision…</div>
          ) : error ? (
            <div className="rounded-lg border border-red-900/50 bg-red-950/30 p-3 text-sm text-red-200">
              {error}
              <div className="mt-1 text-xs text-red-300/80">
                Tip: check <code className="mx-1">/api/releases/latest</code> is reachable.
              </div>
            </div>
          ) : (
            <>
              <div className="font-medium text-slate-200">Why?</div>

              {reasons.length > 0 ? (
                <ul className="list-disc space-y-1 pl-5 text-slate-300">
                  {reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              ) : (
                <div className="text-slate-400">
                  No detailed reasons provided (this is normal if details_json is minimal).
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* ================= KPI Strip ================= */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <Kpi
          label="Success rate"
          value={fmtPct(kSuccess?.candidate ?? null)}
          hint={fmtDeltaPct(kSuccess?.delta ?? null)}
          icon={<CheckCircle2 className="h-4 w-4 text-emerald-400" />}
        />

        <Kpi
          label="Mean duration"
          value={
            kDur?.candidate == null ? "—" : `${fmtNum(kDur.candidate, 1)} ms`
          }
          hint={fmtDeltaNum(kDur?.delta ?? null, " ms", 1)}
          icon={<Clock className="h-4 w-4 text-sky-400" />}
        />

        <Kpi
          label="Safety violations"
          value={kSafety?.candidate == null ? "—" : String(kSafety.candidate)}
          hint={kSafety?.delta == null ? "" : `Δ +${kSafety.delta} vs baseline`}
          icon={<AlertTriangle className="h-4 w-4 text-red-400" />}
          tooltip="If your runner populates safety_violations, regressions can block shipping."
        />

        <Kpi
          label="Episodes"
          value={kEps?.candidate == null ? "—" : String(kEps.candidate)}
          hint={kEps?.delta == null ? "" : `Δ ${kEps.delta} vs baseline`}
          icon={<TrendingUp className="h-4 w-4 text-lime-400" />}
        />
      </div>

      {/* ================= Extra: Time-to-success ================= */}
      <Card className="border-slate-800 bg-slate-950/40">
        <CardHeader>
          <CardTitle className="text-sm text-slate-100">Additional metrics</CardTitle>
        </CardHeader>

        <CardContent className="text-sm text-slate-300">
          <div className="flex flex-wrap gap-4">
            <div>
              <div className="text-slate-400">Time-to-success mean</div>
              <div className="text-slate-100 font-medium">
                {kTts?.candidate == null ? "—" : `${fmtNum(kTts.candidate, 3)} s`}
              </div>
              <div className="text-slate-400 text-xs">
                {kTts?.delta == null ? "" : fmtDeltaNum(kTts.delta, " s", 3)}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
