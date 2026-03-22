# IndiGo Ops Platform

Dual-app React + TypeScript platform with a shared live WebSocket data layer.

| App | Audience | Theme | Auth |
|-----|----------|-------|------|
| **B2C Booking Portal** | Passengers | Light, IndiGo brand | None |
| **B2B AOCC Dashboard** | Ops controllers | Brutalist dark, Bloomberg terminal | Required |

---

## Quick start

```bash
npm install
cp .env.example .env          # fill in VITE_WS_URL + VITE_API_URL
npm run dev                   # http://localhost:5173
```

**Demo credentials** (AOCC login): `AOCC_OPS` / `6E_TERMINAL`

---

## Architecture

```
src/
├── types/          # Domain models — Flight, WsEvent, ThermodynamicMetrics…
├── constants/      # AIRPORTS, SEED_FLIGHTS, WS_CONFIG, theme tokens T
├── utils/          # Pure functions: formatINR, calcDuration, capeColor…
├── store/
│   ├── flightReducer.ts   # Pure reducer — tested independently
│   ├── authStore.ts       # Zustand: session + async login
│   └── navStore.ts        # Zustand: global SPA routing
├── hooks/
│   ├── useLiveFlightData.ts       # ★ WS transport + Lodash throttle batching
│   ├── useCASKRASK.ts             # Financial metrics stream
│   ├── useThermodynamicMetrics.ts # Weather/wx payload stream
│   ├── useSwarmEventLog.ts        # Autobooking event log generator
│   └── useClock.ts                # Live wall-clock
├── styles/
│   └── global.css         # All animations, scrollbars — one source
└── components/
    ├── shared/            # WsStatusBadge (used in both apps)
    ├── b2c/               # B2CNav, SearchHero, FlightCard, B2CPortal
    └── b2b/               # AOCCLogin, AOCCHeader, StatsBar, FlightTable,
                           # CASKRASKPanel, ThermoPanel, SwarmStream,
                           # NetworkPanel, AOCCDashboard
```

---

## The throttle engine — `useLiveFlightData`

The Autobooking Swarm fires ~30 WebSocket events per second. Without
batching this would trigger ~30 React re-renders per second — certain DOM
thrash on the AOCC flight table.

**Solution:** every incoming event is pushed to `pendingUpdates` (a `useRef`
— no render cost). `_.throttle(flush, 500, { trailing: true })` drains the
buffer at most once every 500 ms into a single `dispatch({ type: "BATCH" })`.

```
Normal mode (2 evt/s):          Swarm mode (30 evt/s):
  evt ─┐                          evt evt evt evt evt evt ─┐
       │                          evt evt evt evt evt evt   │
  500ms flush → 1 render          500ms flush → 1 render  ←┘  (30 → 1)
```

To connect a real FastAPI WebSocket, replace the `setInterval` blocks with:

```ts
const ws = new WebSocket(import.meta.env.VITE_WS_URL);
ws.onmessage = (e) => enqueue(JSON.parse(e.data) as WsEvent);
ws.onopen    = ()  => setConnected(true);
ws.onclose   = ()  => setConnected(false);
return () => ws.close();
```

---

## State management

| Store | Purpose | Persistence |
|-------|---------|-------------|
| `flightReducer` | Pure reducer consumed by `useLiveFlightData` | In-memory |
| `useAuthStore` (Zustand) | Operator session, login/logout | In-memory (add `persist` middleware for refresh-safe sessions) |
| `useNavStore` (Zustand) | Active view (`b2c` \| `login` \| `aocc`) | In-memory |

### Adding `persist` for auth (production recommendation)

```ts
import { persist } from "zustand/middleware";

export const useAuthStore = create(
  persist<AuthState>(
    (set) => ({ ... }),
    { name: "aocc-auth", storage: createJSONStorage(() => sessionStorage) }
  )
);
```

---

## Charts — CASK vs RASK

`CASKRASKPanel` uses Recharts `<LineChart>`. Two decisions matter:

1. **`isAnimationActive={false}`** on both `<Line>` elements — prevents Recharts
   triggering a full SVG re-draw animation every 1.8 s when a new data point
   arrives. Without this, the chart visibly flickers.

2. **Rolling 35-point window** in `useCASKRASK` — `prev.slice(-34)` keeps memory
   bounded regardless of session length.

---

## Network scope

Routing is restricted to four airports:

| Code | City | Terminal |
|------|------|----------|
| DEL  | Delhi (Indira Gandhi Intl) | T2 |
| BOM  | Mumbai (CSMIA) | T1 |
| CCU  | Kolkata (NSCBI) | T2 |
| MAA  | Chennai International | T3 |

To extend the scope, add to `AIRPORTS` in `src/constants/index.ts` and add
seed flights to `SEED_FLIGHTS`. TypeScript's `AirportCode` union type will
surface every place that needs updating at compile time.

---

## Testing

```bash
npm test              # run all tests once (CI mode)
npm run test:watch    # watch mode for TDD
```

Tests live in `tests/core.test.ts` and cover:

- `calcDuration`, `formatINR`, `capeColor/Severity`, `hdwindLabel/Color`, `clamp`, `loadColor`
- `flightReducer` — PRICE_UPDATE, SEAT_SOLD, price clamping, zero-seat floor, multi-event batching

The reducer and utils are pure functions with zero React dependencies — they
run in Vitest's `node` environment, no jsdom needed.

---

## Build & deploy

```bash
npm run build         # TypeScript check + Vite bundle → dist/
npm run preview       # serve dist/ locally to verify

# Docker (example)
docker build -t indigo-ops .
docker run -p 80:80 --env-file .env indigo-ops
```

Vite's `manualChunks` splits vendor bundles for optimal CDN caching:

| Chunk | Libraries |
|-------|-----------|
| `vendor-react` | react, react-dom |
| `vendor-charts` | recharts |
| `vendor-state` | zustand |
| `vendor-utils` | lodash |
| `vendor-icons` | lucide-react |

---

## Connecting the FastAPI backend

Expected WebSocket message shape:

```json
{ "type": "PRICE_UPDATE", "fid": "6E-201", "delta": -120 }
{ "type": "SEAT_SOLD",    "fid": "6E-512", "count": 2    }
```

Expected REST endpoints:

```
POST /api/v1/auth/token          → { access_token, token_type }
GET  /api/v1/flights             → Flight[]
GET  /api/v1/flights/{id}/thermo → ThermodynamicMetrics
```

All types are exported from `src/types/index.ts` — share them with the
backend team or generate from a shared OpenAPI schema.
