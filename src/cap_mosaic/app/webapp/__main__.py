"""Run the Mosaic Estimator web app.

    python -m cap_mosaic.app.webapp            # http://127.0.0.1:8000
    python -m cap_mosaic.app.webapp --port 9000

Needs the web extra: ``pip install -e .[web]`` (fastapi, uvicorn, python-multipart).
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cap-mosaic-estimator", description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)
    import uvicorn

    print(f"Mosaic Estimator -> http://{args.host}:{args.port}", flush=True)
    uvicorn.run("cap_mosaic.app.webapp.server:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
