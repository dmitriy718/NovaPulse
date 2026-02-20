import ws from "k6/ws";
import { check } from "k6";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8080";
const READ_KEY = __ENV.READ_KEY || "";
const WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://");

export const options = {
  scenarios: {
    ws_fanout: {
      executor: "constant-vus",
      vus: 25,
      duration: "60s",
    },
  },
  thresholds: {
    checks: ["rate>0.98"],
  },
};

export default function () {
  const url = `${WS_URL}/ws/live`;
  const params = {
    headers: READ_KEY ? { "X-API-Key": READ_KEY } : {},
  };

  const res = ws.connect(url, params, function (socket) {
    let gotMessage = false;

    socket.on("message", function () {
      gotMessage = true;
      socket.close();
    });

    socket.setTimeout(function () {
      socket.close();
    }, 5000);
  });

  check(res, {
    "ws handshake 101": (r) => r && r.status === 101,
  });
}
