"""Point a local slot at a workflow that already exists in the workspace, so a fresh clone updates it in place
instead of creating a new one (a workspace holds a limited number of workflows).

    python dev/attach_slot.py                      # list the workspace's workflows: name, agent id, last update
    python dev/attach_slot.py yasar-exp-date       # write that workflow's ids to .freya-agents.json under this slot

`.freya-agents.json` is local (ignored by git): it maps a slot to {workflow_id, agent_id}, and freya.save_workflow
creates a workflow for any slot it does not find there. Needs FREYA_API_KEY (source env.sh). Prints no secrets.
On a python.org build of Python for macOS, run `export SSL_CERT_FILE=/etc/ssl/cert.pem` first.
"""
import json, pathlib, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
import freya


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    items = freya.api("GET", "/api/v2/workflow", workspaceId=freya.workspace_id())["workflows"]
    if not args:
        for w in sorted(items, key=lambda w: str(w.get("updatedAt") or ""), reverse=True):
            print(f"{str(w.get('name'))[:44]:<44} agent {w.get('agentId')}  updated {str(w.get('updatedAt') or '')[:19]}")
        print(f"\n{len(items)} workflow(s). A slot is the name without its time stamp.")
        return 0
    slot = args[0]
    hits = [w for w in items if str(w.get("name", "")).startswith(slot + " ") or w.get("name") == slot]
    if len(hits) != 1:
        sys.exit(f"{len(hits)} workflow(s) are named {slot!r}: " + ", ".join(str(w.get("name")) for w in hits))
    path = KIT / ".freya-agents.json"
    state = json.loads(path.read_text()) if path.exists() else {}
    state[slot] = {"workflow_id": hits[0]["id"], "agent_id": hits[0]["agentId"]}
    path.write_text(json.dumps(state, indent=1))
    print(f"slot {slot} -> agent {hits[0]['agentId']} ({hits[0]['name']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
