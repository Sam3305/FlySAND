import React from "react";
import { useNavStore, useAuthStore } from "./store";
import { B2CPortal }        from "./components/b2c/B2CPortal";
import { UnifiedLogin }     from "./components/UnifiedLogin";
import { AOCCDashboard }    from "./components/b2b/AOCCDashboard";
import { SeatSelectionPage } from "./components/b2c/SeatSelectionPage";
import { PaymentPage }       from "./components/b2c/PaymentPage";
import { OpsFlightsPage }    from "./components/ops/OpsFlightsPage";
import { AgentOrchestratorPage } from "./components/ops/AgentOrchestratorPage";
import { useBookingStore }   from "./store/bookingStore";

const App: React.FC = () => {
  const view          = useNavStore((s) => s.view);
  const authenticated = useAuthStore((s) => s.authenticated);
  const flight        = useBookingStore((s) => s.flight);

  const resolvedView = view === "aocc" && !authenticated ? "login" : view;

  if ((resolvedView === "seat-selection" || resolvedView === "payment") && !flight) {
    return <B2CPortal />;
  }

  return (
    <>
      {resolvedView === "b2c"            && <B2CPortal />}
      {resolvedView === "login"          && <UnifiedLogin />}
      {resolvedView === "aocc"           && <AOCCDashboard />}
      {resolvedView === "seat-selection" && <SeatSelectionPage flight={flight!} />}
      {resolvedView === "payment"        && <PaymentPage       flight={flight!} />}
      {resolvedView === "ops-login"      && <UnifiedLogin />}
      {resolvedView === "ops-flights"    && <OpsFlightsPage />}
      {resolvedView === "ops-agents"     && <AgentOrchestratorPage />}
    </>
  );
};

export default App;
