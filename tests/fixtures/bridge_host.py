"""Test-only JSON-lines carrier; NOT a production API or server."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from r6_rebuild.application import Application
from r6_rebuild.bridge import BridgeAPI

app=Application(sys.argv[1]);api=BridgeAPI(app)
try:
    for line in sys.stdin:
        request=json.loads(line)
        result=api.invoke(request['action'],request.get('payload',{}))
        print(json.dumps(result,ensure_ascii=True),flush=True)
finally:
    api._close()
