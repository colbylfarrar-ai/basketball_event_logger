"""AST sweep for cross-section variable leaks after a _seg conversion.

Under one long scroll, section B could read a name section A happened to define.
Under lazy if-dispatch only one body runs, so that read is a NameError the
moment a coach opens B. Find them before a coach does.

Usage: leak_sweep.py <page.py> [flag_name]
"""
import ast
import builtins
import sys

path = sys.argv[1]
flag = sys.argv[2] if len(sys.argv) > 2 else "_eetool"
tree = ast.parse(open(path, encoding="utf-8").read())


def bound_in(node):
    """Every name a nested scope binds itself: params, locals, comprehension
    targets, nested def names, imports."""
    out = set()
    args = getattr(node, "args", None)
    if args is not None:
        for a in (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
                  + ([args.vararg] if args.vararg else [])
                  + ([args.kwarg] if args.kwarg else [])):
            out.add(a.arg)
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
            a3 = getattr(n, "args", None)
            if a3 is not None:
                for a in (list(a3.posonlyargs) + list(a3.args)
                          + list(a3.kwonlyargs)
                          + ([a3.vararg] if a3.vararg else [])
                          + ([a3.kwarg] if a3.kwarg else [])):
                    out.add(a.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.Lambda):
            a2 = n.args
            for a in (list(a2.posonlyargs) + list(a2.args) + list(a2.kwonlyargs)):
                out.add(a.arg)
    return out


def free_loads(node):
    """Names this subtree READS without binding anywhere inside it."""
    loads = {n.id for n in ast.walk(node)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return loads - bound_in(node)


def is_section(node):
    if not isinstance(node, ast.If):
        return None
    t = node.test
    if (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
            and t.left.id == flag and t.comparators
            and isinstance(t.comparators[0], ast.Constant)):
        return t.comparators[0].value
    return None


sections, outside = {}, []
for node in tree.body:
    lbl = is_section(node)
    (sections.__setitem__(lbl, node) if lbl else outside.append(node))

outside_assigned = set()
for node in outside:
    outside_assigned |= bound_in(node)

owned = {lbl: bound_in(n) for lbl, n in sections.items()}
built = set(dir(builtins))

bad = 0
for lbl, node in sections.items():
    for name in sorted(free_loads(node)):
        if name in built or name in outside_assigned:
            continue
        others = [o for o in sections if name in owned[o] and o != lbl]
        print(f"{'LEAK ' if others else 'UNDEF'} [{lbl}] reads '{name}'"
              + (f", only assigned in {others}" if others else
                 " — assigned nowhere at module scope"))
        bad += 1

print(f"\nsections: {list(sections)}")
print("CLEAN" if not bad else f"{bad} problem(s)")
sys.exit(1 if bad else 0)
