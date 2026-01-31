import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { Overview } from "@/pages/Overview";
import { Runs } from "@/pages/Runs";
import { Gates } from "@/pages/Gates";
import { Settings } from "@/pages/Settings";
import { RunDetail } from "@/pages/RunDetail";
import { GateDetail } from "@/pages/GateDetail";
function Placeholder({ title }: { title: string }) {
  return (
    <div className="text-slate-200">
      <div className="text-lg font-semibold">{title}</div>
      <div className="mt-1 text-sm text-slate-400">
        Coming soon…
      </div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/gates" element={<Gates />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/gates/:id" element={<GateDetail />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}