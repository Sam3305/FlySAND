import React, { useEffect, useState } from "react";
import { API_BASE } from "../../constants";
import type { DashboardStats } from "../../types";

import { AOCCHeader }      from "./AOCCHeader";
import { DailyBriefing }   from "./DailyBriefing";
import { CFOPanel }        from "./CFOPanel";
import { NetworkPanel }    from "./NetworkPanel";
import { TrendingDown, IndianRupee, PieChart, Activity } from "lucide-react";

export const AOCCDashboard: React.FC = () => {
  const [stats,   setStats]   = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch_ = async () => {
      try {
        const res  = await fetch(`${API_BASE}/api/v1/dashboard/stats`);
        const data = await res.json();
        setStats(data);
      } catch { /* backend not ready */ }
      finally { setLoading(false); }
    };
    fetch_();
    const t = setInterval(fetch_, 30_000);
    return () => clearInterval(t);
  }, []);

  const fmt = (n: number) =>
    n >= 1_00_00_000 ? `₹${(n / 1_00_00_000).toFixed(1)}Cr`
    : n >= 1_00_000  ? `₹${(n / 1_00_000).toFixed(1)}L`
    : `₹${n.toLocaleString("en-IN")}`;

  return (
    <div style={{
      minHeight: "100vh",
      background: "#F4F6FB",
      display: "flex",
      flexDirection: "column",
      fontFamily: "'Barlow', 'Inter', system-ui, sans-serif",
    }}>
      <AOCCHeader />

      {/* Main content */}
      <div style={{ flex: 1, padding: "20px 24px", overflowY: "auto" }}>

        {/* KPI Cards Row */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 16,
          marginBottom: 20,
        }}>
          <KPICard
            icon={<IndianRupee size={18} />}
            label="Total Revenue"
            value={stats ? fmt(stats.total_revenue_inr) : "—"}
            sub={stats ? `${stats.total_bookings.toLocaleString()} bookings` : ""}
            color="#0F3CC9"
            loading={loading}
          />
          <KPICard
            icon={<TrendingDown size={18} />}
            label="Total Cost"
            value={stats ? fmt(stats.total_cost_inr) : "—"}
            sub={stats ? `${stats.total_flights.toLocaleString()} flights` : ""}
            color="#DC2626"
            loading={loading}
          />
          <KPICard
            icon={<PieChart size={18} />}
            label="Contribution Margin"
            value={stats ? `${stats.margin_pct >= 0 ? "+" : ""}${stats.margin_pct.toFixed(1)}%` : "—"}
            sub={stats ? fmt(stats.contribution_inr) : ""}
            color={stats && stats.margin_pct >= 10 ? "#059669" : stats && stats.margin_pct >= 0 ? "#D97706" : "#DC2626"}
            loading={loading}
          />
          <KPICard
            icon={<Activity size={18} />}
            label="System Load Factor"
            value={stats ? `${stats.system_lf_pct.toFixed(1)}%` : "—"}
            sub={stats ? `${stats.active_routes} routes active` : ""}
            color={stats && stats.system_lf_pct >= 80 ? "#059669" : stats && stats.system_lf_pct >= 50 ? "#D97706" : "#DC2626"}
            loading={loading}
          />
        </div>

        {/* Main Grid: Daily Briefing + Side Panels */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 380px",
          gap: 16,
          alignItems: "start",
        }}>
          {/* Left: Daily Briefing */}
          <DailyBriefing />

          {/* Right: Stacked cards */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ minHeight: 260 }}>
              <CFOPanel />
            </div>
            <div style={{ minHeight: 260 }}>
              <NetworkPanel />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};


/* ── KPI Card ─────────────────────────────────────────────────────────────── */

interface KPICardProps {
  icon:     React.ReactNode;
  label:    string;
  value:    string;
  sub:      string;
  color:    string;
  loading:  boolean;
}

const KPICard: React.FC<KPICardProps> = ({ icon, label, value, sub, color, loading }) => (
  <div style={{
    background: "#fff",
    borderRadius: 14,
    border: "1px solid #EEF0F7",
    boxShadow: "0 1px 4px rgba(0,0,0,0.04)",
    padding: "18px 20px",
    display: "flex",
    alignItems: "center",
    gap: 14,
  }}>
    <div style={{
      width: 42, height: 42, borderRadius: 12,
      background: `${color}10`,
      display: "flex", alignItems: "center", justifyContent: "center",
      color,
      flexShrink: 0,
    }}>
      {icon}
    </div>
    <div>
      <div style={{ fontSize: 11, color: "#6B7280", fontWeight: 500, marginBottom: 2 }}>
        {label}
      </div>
      {loading ? (
        <div style={{ fontSize: 13, color: "#9CA3AF" }}>Loading…</div>
      ) : (
        <>
          <div style={{ fontSize: 20, fontWeight: 800, color: "#1A1A2E", lineHeight: 1 }}>
            {value}
          </div>
          {sub && (
            <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 3 }}>
              {sub}
            </div>
          )}
        </>
      )}
    </div>
  </div>
);
