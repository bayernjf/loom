"""Audit instrument: per-operation gate chain.

For every HTTP operation this lists the *injected dependencies* (excluding the session
provider and the handler itself) and, for each dependency, whether its own source
performs a role check or a credential check. Anything the chain cannot see is reported as
"not observable at the route", which is not the same as "unguarded" — role enforcement may
still live inside the service function the handler calls, and the report must confirm
those by reading (see docs/23 §C).
"""

import inspect
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.routing import APIRoute

from app.main import app

SKIP = {"get_session", "MetricsMiddleware"}
CRED_MARKERS = ("require_agent_key", "verify_key", "get_current_staff", "require_internal_actor", "staff_auth_context")
ROLE_MARKER = "require_any_role"


def collect(routes, out):
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        else:
            inner = getattr(r, "routes", None) or getattr(getattr(r, "original_router", None), "routes", None)
            if inner:
                collect(inner, out)
    return out


def describe(fn):
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        src = ""
    name = getattr(fn, "__name__", "?")
    kind = "other"
    if any(m in src for m in CRED_MARKERS) or any(m in name for m in CRED_MARKERS):
        kind = "credential"
    elif ROLE_MARKER in src:
        kind = "role"
    elif name in {"internal_gate"}:
        kind = "credential"
    return {"name": name, "kind": kind}


def sub_deps(dependant, acc, depth=0):
    for sub in getattr(dependant, "dependencies", []) or []:
        fn = getattr(sub, "call", None) or getattr(sub, "dependency", None)
        if callable(fn):
            info = describe(fn)
            if info["name"] not in SKIP:
                acc.append(info)
        sub_deps(sub, acc, depth + 1)
    return acc


rows = []
for r in collect(list(app.routes), []):
    for verb in sorted(x for x in (r.methods or set()) if x.lower() in ("get", "post", "put", "patch", "delete")):
        chain = sub_deps(r.dependant, [])
        names = {c["name"]: c["kind"] for c in chain}
        handler_src = ""
        try:
            handler_src = inspect.getsource(r.endpoint)
        except (OSError, TypeError):
            pass
        rows.append({
            "op": f"{verb.upper()} {r.path}",
            "verb": verb.upper(),
            "deps": names,
            "role_in_handler": ROLE_MARKER in handler_src,
            "handler": r.endpoint.__name__,
            "module": r.endpoint.__module__.replace("app.", ""),
        })

writes = [x for x in rows if x["verb"] != "GET"]
kind_of_op = {}
for x in rows:
    kinds = set(x["deps"].values())
    if "credential" in kinds:
        k = "has-credential-dep"
    elif x["role_in_handler"]:
        k = "role-in-handler-only"
    elif kinds and kinds != {"other"}:
        k = "other-dep"
    else:
        k = "no-route-level-gate"
    kind_of_op.setdefault(k, []).append(x["op"])

print("operations:", len(rows), "| writes:", len(writes), "| reads:", len(rows) - len(writes))
for k, v in sorted(kind_of_op.items(), key=lambda kv: -len(kv[1])):
    print(f"\n{k}: {len(v)} ops")
    if k in ("has-credential-dep", "role-in-handler-only"):
        for op in v:
            print("   ", op)
print("\n--- distinct dependency names seen across all ops ---")
allnames = {}
for x in rows:
    for n, kind in x["deps"].items():
        allnames.setdefault(kind, set()).add(n)
for kind, names in allnames.items():
    print(f"  {kind}: {sorted(names)}")
pathlib.Path("/tmp/audit_gates.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
print("\nfull dump -> /tmp/audit_gates.json")
