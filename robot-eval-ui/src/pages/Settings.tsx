import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function Settings() {
  return (
    <div className="space-y-4">
      <Card className="border-slate-800 bg-slate-950/40">
        <CardHeader>
          <CardTitle className="text-sm text-slate-100">Settings</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-slate-300">
          Next: API base URL, theme toggle, and UI preferences.
        </CardContent>
      </Card>
    </div>
  );
}
