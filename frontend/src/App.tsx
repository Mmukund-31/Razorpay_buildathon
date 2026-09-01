import { NavLink, Route, Routes } from "react-router-dom";
import AuditLedger from "./pages/AuditLedger";
import Benchmark from "./pages/Benchmark";
import CommandCenter from "./pages/CommandCenter";
import DecisionTrace from "./pages/DecisionTrace";
import RecoveryCase from "./pages/RecoveryCase";
import RecoveryQueue from "./pages/RecoveryQueue";
import Simulation from "./pages/Simulation";

const NAV_ITEMS = [
  { to: "/", label: "Command Center", exact: true },
  { to: "/queue", label: "Recovery Queue" },
  { to: "/benchmark", label: "Benchmark" },
  { to: "/audit", label: "Audit Ledger" },
  { to: "/simulation", label: "Simulation" },
];

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold tracking-tight">RecoveryOS</h1>
        <nav className="mt-2 flex gap-4 text-sm text-slate-400">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.exact}
              className={({ isActive }) => (isActive ? "text-slate-100" : "hover:text-slate-200")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<CommandCenter />} />
          <Route path="/queue" element={<RecoveryQueue />} />
          <Route path="/cases/:caseId" element={<RecoveryCase />} />
          <Route path="/cases/:caseId/trace" element={<DecisionTrace />} />
          <Route path="/benchmark" element={<Benchmark />} />
          <Route path="/audit" element={<AuditLedger />} />
          <Route path="/simulation" element={<Simulation />} />
        </Routes>
      </main>
    </div>
  );
}
