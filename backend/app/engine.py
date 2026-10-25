"""Bridge to the C++ engine (JSON over stdin/stdout). Falls back to an
equivalent pure-Python implementation if the binary is not built, so the app
still runs on hosts without a compiler."""
import heapq
import json
import os
import subprocess

from . import config


def available():
    return os.path.isfile(config.ENGINE_PATH) and os.access(config.ENGINE_PATH, os.X_OK)


def _call(req):
    p = subprocess.run([config.ENGINE_PATH], input=json.dumps(req), capture_output=True, text=True, timeout=10)
    if p.returncode != 0:
        raise RuntimeError(f"engine failed: {p.stdout or p.stderr}")
    return json.loads(p.stdout)


def _rec(r):
    return {"id": r["id"], "prn": r.get("prn", ""), "graduation_year": r.get("graduation_year", 0),
            "status": r.get("status", ""), "priority": r.get("priority", 0)}


def search_prn(records, prn):
    """Return the alumni id for an exact PRN, or None."""
    recs = [_rec(r) for r in records]
    if available():
        return _call({"cmd": "search", "prn": prn, "records": recs})["id"]
    for r in recs:
        if r["prn"] == prn:
            return r["id"]
    return None


def sort_ids(records, key):
    recs = [_rec(r) for r in records]
    if available():
        return _call({"cmd": "sort", "key": key, "records": recs})["ids"]
    rank = {"PENDING": 0, "COMPLETED": 2}
    keyf = {"graduation_year": lambda r: r["graduation_year"],
            "status": lambda r: rank.get(r["status"], 1),
            "priority": lambda r: -r["priority"]}.get(key, lambda r: r["prn"])
    return [r["id"] for r in sorted(recs, key=keyf)]


def pending_list(records, remove=()):
    recs = [_rec(r) for r in records]
    if available():
        return _call({"cmd": "pending_list", "records": recs, "remove": list(remove)})["ids"]
    return [r["id"] for r in recs if r["status"] == "PENDING" and r["id"] not in set(remove)]


def schedule(records, batch_size):
    """Priority queue -> circular queue. Returns {'order': [...], 'batches': [[...]]}."""
    recs = [_rec(r) for r in records]
    if available():
        return _call({"cmd": "schedule", "batch_size": batch_size, "records": recs})
    heap = [(-r["priority"], r["id"]) for r in recs]
    heapq.heapify(heap)
    order = [heapq.heappop(heap)[1] for _ in range(len(heap))]
    bs = max(1, batch_size)
    return {"order": order, "batches": [order[i:i + bs] for i in range(0, len(order), bs)]}


def undo_top(action_ids):
    """action_ids oldest -> newest; returns the id the stack pops (newest) or None."""
    if available():
        return _call({"cmd": "undo", "actions": list(action_ids)})["action_id"]
    return action_ids[-1] if action_ids else None
