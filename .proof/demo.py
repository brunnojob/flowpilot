import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def run(argv, expected=0):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode != expected:
        raise RuntimeError(result.stderr + result.stdout)
    return result.stdout

with tempfile.TemporaryDirectory() as temp:
    project=Path(temp)/'workflow'
    run(['flowpilot','init',str(project)])
    first=json.loads(run(['flowpilot','-p',str(project),'run','hello','--json']))
    second=json.loads(run(['flowpilot','-p',str(project),'run','hello','--json']))
    assert first['status'] == second['status'] == 'success'
    with sqlite3.connect(project / '.flowpilot/flowpilot.db') as database:
        outputs=[json.loads(row[0]) for row in database.execute("SELECT output FROM step_runs WHERE step_id='greeting' ORDER BY id")]
        count=json.loads(database.execute("SELECT value FROM workflow_state WHERE workflow='hello' AND key='count'").fetchone()[0])
    assert '#1' in outputs[0] and '#2' in outputs[1] and count == 2
    print(json.dumps({'first':first,'second':second,'outputs':outputs,'persisted_count':count},sort_keys=True))
