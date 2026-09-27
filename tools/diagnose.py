"""Read-only Times Gate diagnostics. Never changes a device setting."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keeper.protocol import Client

parser = argparse.ArgumentParser()
parser.add_argument("--ip")
parser.add_argument("--output", type=Path, default=Path("artifacts/device-diagnostics.json"))
args = parser.parse_args()
ip = args.ip
if not ip:
    old = Path(os.getenv("APPDATA", str(Path.home()))) / "DivoomKeeper" / "config.json"
    if old.exists():
        ip = json.loads(old.read_text(encoding="utf-8"))["device_ip"]
if not ip:
    raise SystemExit("No device configured; pass --ip")
client = Client(ip, timeout=2)
results = {"ip": ip, "read_only": True, "responses": {}}
for command in ["Channel/GetAllConf", "Channel/GetIndex", "Device/GetDeviceTime"]:
    try:
        results["responses"][command] = client.command({"Command": command})
    except Exception as error:
        results["responses"][command] = {"error": str(error)}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=True))
