import React from "react";
import { useNavStore, useAuthStore } from "./store";
import { useLiveFlightData }         from "./hooks";
import { B2CPortal }                 from "./components/b2c/B2CPortal";
import { AOCCLogin }                 from "./components/b2b/AOCCLogin";
import { AOCCDashboard }             from "./components/b2b/AOCCDashboard";
import { SeatSelectionPage }         from "./components/b2c/SeatSelectionPage";
import { PaymentPage }               from "./components/b2c/PaymentPage";
import { OpsLogin }                  from "./components/ops/OpsLogin";
import { OpsFlightsPage }            from "./components/ops/OpsFlightsPage";
import { useBookingStore }           from "./store/bookingStore";

const App: React.FC = () => {
  const view          = useNavStore((s) => s.view);
  const authenticated = useAuthStore((s) => s.authenticated);
  const flight        = useBookingStore((s) => s.flight);
  const live          = useLiveFlightData();

  const resolvedView = view === "aocc" && !authenticated ? "login" : view;

  if ((resolvedView === "seat-selection" || resolvedView === "payment") && !flight) {
    return <B2CPortal live={live} />;
  }

  return (
    <>
      {resolvedView === "b2c"            && <B2CPortal         live={live} />}
      {resolvedView === "login"          && <AOCCLogin />}
      {resolvedView === "aocc"           && <AOCCDashboard      live={live} />}
      {resolvedView === "seat-selection" && <SeatSelectionPage  flight={flight!} />}
      {resolvedView === "payment"        && <PaymentPage        flight={flight!} />}
      {resolvedView === "ops-login"      && <OpsLogin />}
      {resolvedView === "ops-flights"    && <OpsFlightsPage />}
    </>
  );
};

export default App;
