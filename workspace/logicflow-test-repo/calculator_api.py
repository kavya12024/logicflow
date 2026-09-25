"""Small JSON HTTP API that exposes the calculator to a browser frontend."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from calculator import add, divide, multiply, subtract


OPERATIONS = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
}


def calculate(operation: str, first: float, second: float) -> float:
    """Run a named calculator operation with predictable validation errors."""
    if operation not in OPERATIONS:
        raise ValueError(f"Unsupported operation: {operation}")
    if operation == "divide" and second == 0:
        raise ValueError("Cannot divide by zero")
    return OPERATIONS[operation](first, second)


class CalculatorHandler(BaseHTTPRequestHandler):
    """Handle POST /calculate requests from the browser frontend."""

    def do_POST(self) -> None:
        if self.path != "/calculate":
            self._send_json(404, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload: Dict[str, Any] = json.loads(self.rfile.read(length))
            result = calculate(
                str(payload["operation"]),
                float(payload["first"]),
                float(payload["second"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._send_json(400, {"error": str(error)})
            return

        self._send_json(200, {"result": result})

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the calculator API until interrupted."""
    server = ThreadingHTTPServer((host, port), CalculatorHandler)
    print(f"Calculator API running at http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()