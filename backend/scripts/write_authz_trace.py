"""Audit instrument: trace each write operation's authorization chain.

The repo enforces roles through several different mechanisms (`rbac.require_any_role`,
local helpers like `_require_ops` / `_require_owner`, inline `X not in actor.roles`
checks, route-level `internal_gate(...)` / `require_internal_actor(...)`). This walks the
handler, the service function it calls, and one further level of local `_require_*`
helpers, recording which mechanism and which role string guards each write — so the report
can state exactly how many writes are protected only by a *self-declared* body actor.
"""

import ast
import inspect
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi.routing import APIRoute  # noqa: E402

from app.main import app  # noqa: E402

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

GATE_NAMES = {
    "require_any_role", "require_internal_actor", "internal_gate", "require_sla_view",
    "GateNotAllowed", "PermissionDenied", "RoleNotAllowed",
}


def collect_routes(routes, out):
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        else:
            inner = getattr(r, "routes", None) or getattr(getattr(r, "original_router", None), "routes", None)
            if inner:
                collect_routes(inner, out)
    return out


funcs = {}
for p in APP.rglob("*.py"):
    try:
        tree = ast.parse(p.read_text())
    except SyntaxError:
        continue
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, []).append((str(p.relative_to(APP.parent)), node))


def role_args(call):
    out = set()
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.add(arg.value)
        elif isinstance(arg, (ast.List, ast.Tuple, ast.Set)):
            out.update(el.value for el in arg.elts if isinstance(el, ast.Constant) and isinstance(el.value, str))
        elif isinstance(arg, ast.Attribute):
            out.add(arg.attr.lower())
    return out


def scan(node, depth=0, seen=None):
    seen = seen or set()
    found = []
    for c in ast.walk(node):
        if not isinstance(c, ast.Call):
            continue
        name = getattr(c.func, "attr", None) or getattr(c.func, "id", None)
        if not name:
            continue
        if name in GATE_NAMES or (name.startswith("_require") and name in funcs):
            found.append({"mechanism": name, "roles": sorted(role_args(c))})
        if depth < 2 and name in funcs:
            for _mod, fn in funcs[name]:
                if id(fn) in seen:
                    continue
                seen.add(id(fn))
                found.extend(scan(fn, depth + 1, seen))
    return found


rows = []
for r in collect_routes(list(app.routes), []):
    for verb in sorted(x for x in (r.methods or set()) if x in ("post", "put", "patch", "delete")):
        handler = r.endpoint
        try:
            src = inspect.getsource(handler)
            tree = ast.parse(src)
        except (OSError, TypeError):
            tree = None
        mechanisms, roles = set(), set()
        if tree is not None:
            # inline `SOMETHING not in actor.roles` counts as a gate the handler itself does
            for c in ast.walk(tree):
                if isinstance(c, ast.Compare):
                    txt = ast.unparse(c)
                    if ".roles" in txt:
                        mechanisms.add("inline actor.roles check")
            for g in scan(tree):
                mechanisms.add(g["mechanism"])
                roles.update(g["roles"])
        rows.append({"op": f"{verb.upper()} {r.path}", "handler": handler.__name__,
                     "mechanisms": sorted(mechanisms), "roles": sorted(roles)})

print("write operations:", len(rows))
ungated = [x for x in rows if not x["mechanisms"]]
print("writes with no gate reachable from the handler:", len(ungated))
for x in ungated:
    print(f"   {x['op']:66} handler={x['handler']}")
freq = {}
for x in rows:
    for m in x["mechanisms"]:
        freq[m] = freq.get(m, 0) + 1
print("\ngate mechanism frequency across write ops:", json.dumps(freq, ensure_ascii=False, indent=1))
pathlib.Path("/tmp/audit_write_gates.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
print("full dump -> /tmp/audit_write_gates.json")
