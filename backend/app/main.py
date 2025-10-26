"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .api import configuration, signals, sim
from .config import CONFIG

app = FastAPI(
    title="EUR/USD Signal Simulator",
    version="0.1.0",
    description=(
        "Prototype backend implementing the public API contract for the "
        "EUR/USD 30-second signal simulator."
    ),
)

app.include_router(sim.router)
app.include_router(signals.router)
app.include_router(configuration.router)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    """Simple health endpoint for infrastructure checks."""
    return {"status": "ok", "dataset": CONFIG.simulation.dataset_id}


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    """Provide a simple landing page for root requests."""

    return """
    <!DOCTYPE html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\" />
        <title>EUR/USD Signal Simulator</title>
        <style>
          body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            padding: 3rem 1.5rem;
            background: #0f172a;
            color: #e2e8f0;
            display: flex;
            min-height: 100vh;
            align-items: center;
            justify-content: center;
          }
          main {
            max-width: 32rem;
            background: rgba(15, 23, 42, 0.7);
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 1rem;
            padding: 2.5rem;
            box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.65);
          }
          h1 {
            margin-top: 0;
            font-size: 2rem;
            letter-spacing: 0.04em;
          }
          p {
            line-height: 1.6;
          }
          a {
            color: #38bdf8;
            text-decoration: none;
            font-weight: 600;
          }
          a:hover {
            text-decoration: underline;
          }
          ul {
            padding-left: 1.25rem;
          }
        </style>
      </head>
      <body>
        <main>
          <h1>EUR/USD Signal Simulator API</h1>
          <p>
            The backend service is online. Use the links below to explore the
            interactive documentation or run health checks.
          </p>
          <ul>
            <li><a href=\"/docs\">Interactive API docs</a></li>
            <li><a href=\"/redoc\">ReDoc reference</a></li>
            <li><a href=\"/healthz\">Health status endpoint</a></li>
          </ul>
        </main>
      </body>
    </html>
    """
