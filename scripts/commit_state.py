#!/usr/bin/env python3
"""Stories Library - da lanciare SOLO a giro finito (pagine Notion scritte).
Copia work/pending_state.json in state/last_seen.json e fa commit+push."""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pend = os.path.join(ROOT, "work", "pending_state.json")
if not os.path.exists(pend):
    sys.exit("ERRORE: work/pending_state.json mancante, lo stato non viene toccato")
state_path = os.path.join(ROOT, "state", "last_seen.json")
state = json.load(open(state_path))
state.update(json.load(open(pend)))
json.dump(state, open(state_path, "w"), indent=1, sort_keys=True)
msg = sys.argv[1] if len(sys.argv) > 1 else "Aggiorna last_seen dopo il giro"
subprocess.run(["git", "-C", ROOT, "add", "state/last_seen.json"], check=True)
if subprocess.run(["git", "-C", ROOT, "diff", "--cached", "--quiet"]).returncode:
    subprocess.run(["git", "-C", ROOT, "commit", "-m", msg], check=True)
    for i in range(4):
        if subprocess.run(["git", "-C", ROOT, "push", "-u", "origin", "HEAD"]).returncode == 0:
            break
    else:
        sys.exit("ERRORE: push dello stato fallito")
print("stato aggiornato")
