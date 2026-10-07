"""Run with one worker: one queue owns device writes and schedules."""
import argparse
import logging
import os
from pathlib import Path


def uvicorn_options(host, port):
    # No access log: it would record the OAuth callback query string (authorization code and state).
    return {"host": host, "port": port, "workers": 1, "proxy_headers": False, "access_log": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("KEEPER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("KEEPER_PORT", "8080")))
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("KEEPER_DATA", "server-data")))
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    from keeper.portal import create_app
    import uvicorn
    app = create_app(args.data_dir, demo=args.demo)
    print(f"Portal: http://{args.host}:{args.port} · Token en {args.data_dir.resolve() / 'admin.token'} o KEEPER_TOKEN")
    uvicorn.run(app, **uvicorn_options(args.host, args.port))


if __name__ == "__main__":
    main()
