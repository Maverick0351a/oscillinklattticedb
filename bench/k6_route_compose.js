import http from 'k6/http';
import { sleep } from 'k6';

export const options = {
  vus: __ENV.VUS ? parseInt(__ENV.VUS) : 10,
  duration: __ENV.DURATION || '30s',
};

const BASE = __ENV.URL || 'http://127.0.0.1:8080';
const Q = __ENV.Q || 'What is Oscillink?';

export default function () {
  const r1 = http.post(`${BASE}/v1/latticedb/route`, JSON.stringify({ q: Q }), { headers: { 'Content-Type': 'application/json' } });
  const items = r1.json('candidates') || [];
  const sel = items.slice(0, 3).map((c) => c.lattice_id);
  http.post(`${BASE}/v1/latticedb/compose`, JSON.stringify({ q: Q, lattice_ids: sel }), { headers: { 'Content-Type': 'application/json' } });
  sleep(0.1);
}
