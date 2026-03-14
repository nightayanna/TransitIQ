# TransIQ ML API — Frontend Integration Guide

> **Owner:** Ayanna (ML Engineer)  
> **Base URL:** `https://splenial-kareem-manically.ngrok-free.dev`  
> **Required header on every request:** `ngrok-skip-browser-warning: true`  
> **⚠️ Keep Ayanna's laptop on at all times — the API dies if it restarts and the URL will change.**

---

## Quick Reference

| Endpoint | Method | Who Uses It | Purpose |
|---|---|---|---|
| `/health` | GET | DevOps / debugging | Confirm all 6 models are loaded |
| `/hubs` | GET | Home screen (Abby) | Populate the "Where from / Where to" autocomplete |
| `/plan` | POST | Results screen (Abby) | Get Fastest, Cheapest, Balanced route plans |
| `/predict` | POST | Detail screen (Brit) | Single route prediction (ETA, fare, safety, etc.) |

---

## Base Axios Config (put this in `src/api/transiq.ts`)

```typescript
import axios from 'axios';

const ML_API = axios.create({
  baseURL: 'https://splenial-kareem-manically.ngrok-free.dev',
  headers: {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
  },
  timeout: 10000, // 10s — ML inference can be slow under load
});

export default ML_API;
```

---

## 1. GET `/health`

Use this on app startup to confirm the API is reachable. If it fails, show an offline banner — do not silently fail.

### Request
```
GET /health
Headers: ngrok-skip-browser-warning: true
```

### Sample Response `200 OK`
```json
{
  "status": "healthy",
  "models_loaded": 6,
  "models": {
    "eta": "loaded",
    "fare": "loaded",
    "traffic": "loaded",
    "departure": "loaded",
    "reliability": "loaded",
    "safety": "loaded"
  },
  "uptime_seconds": 3721
}
```

### Usage (React Native)
```typescript
import ML_API from '../api/transiq';

export const checkAPIHealth = async (): Promise<boolean> => {
  try {
    const res = await ML_API.get('/health');
    return res.data.status === 'healthy' && res.data.models_loaded === 6;
  } catch {
    return false;
  }
};
```

---

## 2. GET `/hubs`

Call this once on Home screen mount to populate the origin/destination autocomplete. Do **not** hardcode hub names — this list is the source of truth from Jodel's DB.

### Request
```
GET /hubs
Headers: ngrok-skip-browser-warning: true
```

### Sample Response `200 OK`
```json
{
  "hubs": [
    "Spanish Town",
    "Half Way Tree",
    "Downtown Kingston",
    "Portmore",
    "New Kingston",
    "Constant Spring",
    "Papine",
    "Cross Roads",
    "Old Harbour",
    "Mandeville",
    "May Pen",
    "Montego Bay",
    "Ocho Rios",
    "Port Antonio",
    "Negril"
  ],
  "count": 15
}
```

### Usage (React Native)
```typescript
import ML_API from '../api/transiq';

export const getHubs = async (): Promise<string[]> => {
  const res = await ML_API.get('/hubs');
  return res.data.hubs;
};

// In your Home screen component:
const [hubs, setHubs] = useState<string[]>([]);

useEffect(() => {
  getHubs().then(setHubs);
}, []);
```

---

## 3. POST `/plan` ⭐ Main Endpoint

This is the **core endpoint** — powers the Route Results screen. Send the user's trip inputs, get back three optimised plans: Fastest, Cheapest, Balanced.

### Request Body

| Field | Type | Required | Notes |
|---|---|---|---|
| `start_hub` | string | ✅ | Must match a hub from `/hubs` exactly (case-sensitive) |
| `end_hub` | string | ✅ | Must match a hub from `/hubs` exactly |
| `budget_jmd` | number | ✅ | User's max budget in Jamaican dollars |
| `hour_of_day` | number | ✅ | 0–23 (e.g. `7` = 7am) |
| `day_of_week` | string | ✅ | `"Mon"`, `"Tue"`, `"Wed"`, `"Thu"`, `"Fri"`, `"Sat"`, `"Sun"` |
| `is_weekend` | number | ✅ | `1` if Saturday or Sunday, `0` otherwise |

### Sample Request
```json
{
  "start_hub": "Spanish Town",
  "end_hub": "Half Way Tree",
  "budget_jmd": 500,
  "hour_of_day": 7,
  "day_of_week": "Mon",
  "is_weekend": 0
}
```

### Sample Response `200 OK`
```json
{
  "start_hub": "Spanish Town",
  "end_hub": "Half Way Tree",
  "requested_at": "2026-03-14T07:00:00Z",
  "plans": {
    "fastest": {
      "label": "Fastest",
      "transport_type": "Knutsford Express",
      "eta_minutes": 28,
      "fare_jmd": 450,
      "congestion_level": 3,
      "congestion_label": "Moderate",
      "recommended_departure": "07:15",
      "reliability_score": 0.87,
      "safety_score": 0.91,
      "within_budget": true,
      "summary": "Knutsford Express direct — 28 min, JMD 450"
    },
    "cheapest": {
      "label": "Cheapest",
      "transport_type": "Route Taxi",
      "eta_minutes": 47,
      "fare_jmd": 200,
      "congestion_level": 4,
      "congestion_label": "Heavy",
      "recommended_departure": "07:05",
      "reliability_score": 0.72,
      "safety_score": 0.78,
      "within_budget": true,
      "summary": "Route Taxi via Washington Blvd — 47 min, JMD 200"
    },
    "balanced": {
      "label": "Balanced",
      "transport_type": "JUTC Bus",
      "eta_minutes": 38,
      "fare_jmd": 100,
      "congestion_level": 3,
      "congestion_label": "Moderate",
      "recommended_departure": "07:10",
      "reliability_score": 0.81,
      "safety_score": 0.85,
      "within_budget": true,
      "summary": "JUTC Bus 22 — 38 min, JMD 100"
    }
  }
}
```

### Field → UI Mapping (Results Screen)

| API Field | UI Element | Format |
|---|---|---|
| `label` | Card header badge | `"Fastest"` / `"Cheapest"` / `"Balanced"` |
| `transport_type` | Transport icon + name | Match to icon: Route Taxi 🚕, JUTC 🚌, Knutsford 🚐, JUTA 🏨, Uber 🚗 |
| `eta_minutes` | Big time number | `"28 min"` |
| `fare_jmd` | Price pill | `"JMD 200"` |
| `congestion_label` | Traffic badge | Colour: Low=green, Moderate=amber, Heavy=red, Severe=darkred |
| `recommended_departure` | "Leave at" line | `"Leave at 07:15"` |
| `reliability_score` | Star / bar (0–1) | Multiply by 5 for star rating: `0.87 → 4.4 stars` |
| `safety_score` | Shield icon (0–1) | `> 0.85` = green shield, `0.65–0.85` = amber, `< 0.65` = red |
| `within_budget` | Budget tick/cross | Green tick if `true`, red cross if `false` |
| `summary` | Card subtitle | Display as-is |

### Congestion Level Reference

| `congestion_level` | `congestion_label` | Badge Colour |
|---|---|---|
| 1 | Free Flow | `#22c55e` (green) |
| 2 | Light | `#86efac` (light green) |
| 3 | Moderate | `#f59e0b` (amber) |
| 4 | Heavy | `#ef4444` (red) |
| 5 | Severe | `#7f1d1d` (dark red) |

### Usage (React Native)
```typescript
import ML_API from '../api/transiq';

export interface PlanRequest {
  start_hub: string;
  end_hub: string;
  budget_jmd: number;
  hour_of_day: number;
  day_of_week: string;
  is_weekend: 0 | 1;
}

export interface RoutePlan {
  label: string;
  transport_type: string;
  eta_minutes: number;
  fare_jmd: number;
  congestion_level: number;
  congestion_label: string;
  recommended_departure: string;
  reliability_score: number;
  safety_score: number;
  within_budget: boolean;
  summary: string;
}

export interface PlanResponse {
  start_hub: string;
  end_hub: string;
  requested_at: string;
  plans: {
    fastest: RoutePlan;
    cheapest: RoutePlan;
    balanced: RoutePlan;
  };
}

export const getRoutePlans = async (req: PlanRequest): Promise<PlanResponse> => {
  const now = new Date();
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  const payload = {
    ...req,
    hour_of_day: req.hour_of_day ?? now.getHours(),
    day_of_week: req.day_of_week ?? days[now.getDay()],
    is_weekend: req.is_weekend ?? ([0, 6].includes(now.getDay()) ? 1 : 0),
  };

  const res = await ML_API.post<PlanResponse>('/plan', payload);
  return res.data;
};
```

---

## 4. POST `/predict`

Single route prediction. Use this on the **Travel Plan Detail screen** (Brit) when a user taps a plan card and you need to show the full breakdown for one specific route.

### Request Body

| Field | Type | Required | Notes |
|---|---|---|---|
| `start_hub` | string | ✅ | Origin hub |
| `end_hub` | string | ✅ | Destination hub |
| `transport_type` | string | ✅ | `"Route Taxi"`, `"JUTC Bus"`, `"Knutsford Express"`, `"JUTA"`, `"Uber"` |
| `hour_of_day` | number | ✅ | 0–23 |
| `day_of_week` | string | ✅ | `"Mon"` – `"Sun"` |
| `is_weekend` | number | ✅ | `0` or `1` |

### Sample Request
```json
{
  "start_hub": "Spanish Town",
  "end_hub": "Half Way Tree",
  "transport_type": "Route Taxi",
  "hour_of_day": 7,
  "day_of_week": "Mon",
  "is_weekend": 0
}
```

### Sample Response `200 OK`
```json
{
  "start_hub": "Spanish Town",
  "end_hub": "Half Way Tree",
  "transport_type": "Route Taxi",
  "predictions": {
    "eta_minutes": 47,
    "fare_jmd": 200,
    "congestion_level": 4,
    "congestion_label": "Heavy",
    "recommended_departure": "07:05",
    "reliability_score": 0.72,
    "safety_score": 0.78
  }
}
```

---

## Error Handling

All error responses follow this shape:

```json
{
  "error": true,
  "message": "start_hub 'Waterloo' is not a recognised hub",
  "code": "INVALID_HUB"
}
```

### Error Codes

| Code | Meaning | What to show user |
|---|---|---|
| `INVALID_HUB` | Hub name not found in DB | "Please select a valid location from the list" |
| `SAME_HUB` | Start and end are the same | "Origin and destination can't be the same" |
| `BUDGET_TOO_LOW` | Budget under minimum fare (~JMD 80) | "Minimum budget is JMD 80" |
| `MODEL_ERROR` | ML inference failed | "We couldn't calculate this route. Try again." |
| `NO_ROUTE` | No known route between hubs | "No route found between these locations" |

### Recommended Error Wrapper (React Native)
```typescript
import ML_API from '../api/transiq';
import { PlanRequest, PlanResponse } from './types';

export const getRoutePlansWithFallback = async (
  req: PlanRequest
): Promise<{ data: PlanResponse | null; error: string | null }> => {
  try {
    const data = await ML_API.post<PlanResponse>('/plan', req).then(r => r.data);
    return { data, error: null };
  } catch (err: any) {
    const msg = err?.response?.data?.message ?? 'Could not reach TransIQ API';
    return { data: null, error: msg };
  }
};
```

---

## Home Screen → Results Screen: Full Flow

```
User fills Home screen:
  "From": Spanish Town       → start_hub
  "To":   Half Way Tree      → end_hub
  Budget slider: JMD 500     → budget_jmd
  Time: now (auto)           → hour_of_day, day_of_week, is_weekend

  ↓ tap "Find Routes"

POST /plan  →  { fastest, cheapest, balanced }

  ↓ navigate to Results screen, pass plans as route params

Results screen renders 3 cards using field mapping table above.

  ↓ user taps a card

POST /predict (with transport_type from chosen card)  →  full detail

  ↓ navigate to Detail screen
```

---

## Day-of-Week + is_weekend Helper

Copy this into `src/utils/time.ts` — both Abby and Brit should use the same helper:

```typescript
export const getTripTimeParams = (date: Date = new Date()) => {
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  return {
    hour_of_day: date.getHours(),
    day_of_week: days[date.getDay()],
    is_weekend: [0, 6].includes(date.getDay()) ? 1 : 0,
  };
};

// Usage:
// const { hour_of_day, day_of_week, is_weekend } = getTripTimeParams();
```

---

## Testing the API Right Now

Run these from your terminal to verify everything is live before wiring up the frontend:

```bash
# 1. Health check
curl -s https://splenial-kareem-manically.ngrok-free.dev/health \
  -H "ngrok-skip-browser-warning: true" | python3 -m json.tool

# 2. Get hubs
curl -s https://splenial-kareem-manically.ngrok-free.dev/hubs \
  -H "ngrok-skip-browser-warning: true" | python3 -m json.tool

# 3. Get a plan (copy-paste this whole block)
curl -s -X POST https://splenial-kareem-manically.ngrok-free.dev/plan \
  -H "ngrok-skip-browser-warning: true" \
  -H "Content-Type: application/json" \
  -d '{
    "start_hub": "Spanish Town",
    "end_hub": "Half Way Tree",
    "budget_jmd": 500,
    "hour_of_day": 7,
    "day_of_week": "Mon",
    "is_weekend": 0
  }' | python3 -m json.tool
```

---

## Notes for Richard (Backend / Auth)

- The Spring Boot API (`POST /api/routes`) should call **this ML API's `/plan` endpoint** to get predictions, then merge with route step data from Jodel's DB before returning to the mobile app.
- Do **not** have the React Native app call the ML API directly in production — route it through Spring Boot. For the hackathon demo, direct calls are fine.
- JWT tokens don't need to be sent to the ML API — it has no auth layer.

---

## If the ngrok URL Changes

Ayanna's laptop must stay on. If it restarts and the URL changes:

1. Ayanna posts the new URL in Discord immediately
2. Update `baseURL` in `src/api/transiq.ts`
3. Run `git commit -am "fix: update ngrok URL" && git push`

---

*Last updated: March 14, 2026 — Hackathon Day 1*  
*Questions? Ping Ayanna on Discord.*
