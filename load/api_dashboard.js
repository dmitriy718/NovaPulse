import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8080";
const READ_KEY = __ENV.READ_KEY || "";

export const options = {
  scenarios: {
    api_smoke: {
      executor: "ramping-vus",
      startVUs: 1,
      stages: [
        { duration: "30s", target: 5 },
        { duration: "60s", target: 20 },
        { duration: "30s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: ["p(95)<800"],
  },
};

function headers() {
  return READ_KEY ? { "X-API-Key": READ_KEY } : {};
}

export default function () {
  const common = { headers: headers() };
  const statusRes = http.get(`${BASE_URL}/api/v1/status`, common);
  check(statusRes, {
    "status endpoint 200": (r) => r.status === 200,
  });

  const perfRes = http.get(`${BASE_URL}/api/v1/performance`, common);
  check(perfRes, {
    "performance endpoint 200": (r) => r.status === 200,
  });

  const scannerRes = http.get(`${BASE_URL}/api/v1/scanner`, common);
  check(scannerRes, {
    "scanner endpoint 200": (r) => r.status === 200,
  });

  sleep(1);
}
