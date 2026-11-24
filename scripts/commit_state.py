#!/usr/bin/env python3
"""Stories Library - da lanciare SOLO a giro finito (pagine Notion scritte).

Unisce work/pending_state.json con lo stato su origin/main e fa commit+push
direttamente su main (non sul branch della sessione), cosi' il giro dopo
riparte dallo stato giusto."""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = "state/last_seen.json"


def git(*a, check=True, **kw):
    return subprocess.run(["git", "-C", ROOT, *a], check=check, **kw)


pend_path = os.path.join(ROOT, "work", "pending_state.json")
if not os.path.exists(pend_path):
    sys.exit("ERRORE: work/pending_state.json mancante, lo stato non viene toccato")
pending = json.load(open(pend_path))
msg = sys.argv[1] if len(sys.argv) > 1 else "Aggiorna last_seen dopo il giro"

for attempt in range(4):
    git("fetch", "-q", "origin", "main")
    main_state = json.loads(git("show", f"origin/main:{REL}", capture_output=True).stdout)
    for c, e in pending.items():
        m = main_state.setdefault(c, {})
        m["last_taken_at"] = max(int(m.get("last_taken_at", 0)), int(e.get("last_taken_at", 0)))
        m["ids"] = list(dict.fromkeys(m.get("ids", []) + e.get("ids", [])))[-50:]
        if e.get("last_check"):
            m["last_check"] = max(m.get("last_check", ""), e["last_check"])
    # lavora su main aggiornato, qualunque sia il branch della sessione
    git("checkout", "-q", "-f", "-B", "main", "origin/main")
    json.dump(main_state, open(os.path.join(ROOT, REL), "w"), indent=1, sort_keys=True)
    git("add", REL)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("stato gia' aggiornato")
        sys.exit(0)
    git("-c", "user.name=Stories Library", "-c", "user.email=stories-library@users.noreply.github.com",
        "commit", "-q", "-m", msg)
    if git("push", "-q", "origin", "main", check=False).returncode == 0:
        print("stato aggiornato su main")
        sys.exit(0)
    print(f"push fallito (tentativo {attempt + 1}), riprovo", file=sys.stderr)
sys.exit("ERRORE: push dello stato su main fallito")
