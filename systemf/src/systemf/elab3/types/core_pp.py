"""
Pretty printer for core language terms.

Indent-aware, uses core-specific syntax (not surface syntax).
"""
from .core import (
    CoreApp,
    CoreCase,
    CoreGlobalVar,
    CoreLam,
    CoreLet,
    CoreLit,
    CoreTm,
    CoreTyApp,
    CoreTyLam,
    CoreVar,
    DataAlt,
    DefaultAlt,
    LitAlt,
    NonRec,
    Rec,
)
from .ty import Ty, TyInt, TyString


def _ty_str(ty: Ty) -> str:
    """Get string representation of a type (public wrapper)."""
    from .ty import _ty_repr
    return _ty_repr(ty, 0)


def _ty_str_paren(ty: Ty) -> str:
    """Get string representation of a type, parenthesizing if it contains spaces."""
    s = _ty_str(ty)
    if ' ' in s:
        return f"({s})"
    return s


def pp_core(tm: CoreTm, *, width: int = 2) -> str:
    """Pretty-print a core term with indentation."""
    return "\n".join(_pp(tm, 0, width))


def _pp(tm: CoreTm, depth: int, width: int) -> list[str]:
    """Return lines for the term at given indent depth."""
    ind = " " * (depth * width)

    match tm:
        case CoreLit(value):
            return [f"{ind}{value.v!r}"]

        case CoreVar(id) | CoreGlobalVar(id):
            return [f"{ind}{id.name.surface}"]

        case CoreLam(param, body):
            ty_str = _ty_str(param.ty)
            return [
                *join_expr_lines(f"{ind}\\{param.name.surface} :: {ty_str} -> ", _pp(body, depth + 1, width)),
            ]

        case CoreTyLam(var, body):
            return [
                *join_expr_lines(f"{ind}/\\{_ty_str(var)}. ", _pp(body, depth + 1, width)),
            ]

        case CoreApp(fun, arg):
            fun_lines = _pp_fun(fun, depth, width)
            arg_lines = _pp_arg(arg, depth + 1, width)
            return [_join_app(fun_lines, arg_lines)]

        case CoreTyApp(fun, tyarg):
            fun_lines = _pp_fun(fun, depth, width)
            ty_str = _ty_str_paren(tyarg)
            return [_join_tyapp(fun_lines, ty_str)]

        case CoreLet(NonRec(binder, expr), body):
            return [
                *join_expr_lines(f"{ind}let {binder.name.surface} = ", _pp(expr, depth + 1, width)),
                *join_expr_lines(f"{ind}in ", _pp(body, depth + 1, width)),
            ]

        case CoreLet(Rec(bindings), body):
            lines = [f"{ind}letrec"]
            for b, e in bindings:
                lines.extend(join_expr_lines(f"{ind}{' ' * width}{b.name.surface} = ", _pp(e, depth + 2, width)))
            lines.extend(join_expr_lines(f"{ind}in ", _pp(body, depth + 1, width)))
            return lines

        case CoreCase(scrut, var, res_ty, alts):
            inner_ind = ind + (" " * width)
            lines = [
                f"{ind}case {scrut_id(scrut)} of   -- {var.name.surface} :: {_ty_str(res_ty)}",
            ]
            for i, (alt, rhs) in enumerate(alts):
                sep = "|" if i > 0 else "{"
                alt_str = _pp_alt(alt)
                rhs_lines = _pp(rhs, depth + 3, width)
                lines.extend(join_expr_lines(f"{inner_ind} {sep} {alt_str} -> ", rhs_lines))
            lines.append(f"{inner_ind} }}")
            return lines

        case _:
            return [f"{ind}<??? {type(tm).__name__}>"]


def _pp_fun(tm: CoreTm, depth: int, width: int) -> list[str]:
    """Print the function position of an application.

    Parenthesize if it's not a simple head (var, global, app, tyapp).
    """
    match tm:
        case CoreVar() | CoreGlobalVar() | CoreApp() | CoreTyApp():
            return _pp(tm, depth, width)
        case _:
            return _pp_paren(tm, depth, width)


def _pp_arg(tm: CoreTm, depth: int, width: int) -> list[str]:
    """Print an argument position — parenthesize if not atomic."""
    match tm:
        case CoreVar() | CoreGlobalVar() | CoreLit():
            return _pp(tm, depth, width)
        case _:
            return _pp_paren(tm, depth, width)


def _pp_paren(tm: CoreTm, depth: int, width: int) -> list[str]:
    """Parenthesize a sub-expression, collapsing multi-line to compact single-line."""
    lines = _pp(tm, depth, width)
    if len(lines) == 1:
        return [f"({lines[0].strip()})"]
    # Multi-line: build a compact single-line representation
    text = " ".join(l.strip() for l in lines)
    return [f"({text})"]


def _join_app(fun_lines: list[str], arg_lines: list[str]) -> str:
    """Join function and argument lines into a single application line."""
    if len(fun_lines) == 1 and len(arg_lines) == 1:
        return f"{fun_lines[0]} {arg_lines[0].lstrip()}"
    # Multi-line: keep function head, indent args below
    return "\n".join(fun_lines + arg_lines)


def _join_tyapp(fun_lines: list[str], ty_str: str) -> str:
    """Join function and type argument."""
    if len(fun_lines) == 1:
        return f"{fun_lines[0]} @{ty_str}"
    return "\n".join(fun_lines + [f"  @{ty_str}"])


def _pp_alt(alt) -> str:
    match alt:
        case DataAlt(con=con, vars=vars):
            if vars:
                return f"{con.surface} {' '.join(v.name.surface for v in vars)}"
            return con.surface
        case LitAlt(lit):
            return repr(lit.v)
        case DefaultAlt():
            return "_"
        case _:
            return "<???>"


def scrut_id(tm: CoreTm) -> str:
    """Extract scrutinee identifier string."""
    match tm:
        case CoreVar(id) | CoreGlobalVar(id):
            return id.name.surface
        case _:
            return "..."


def join_expr_lines(line: str, expr_lines: list[str]) -> list[str]:
    """Join the first line of an expression with a preceding line, if possible."""
    if not expr_lines:
        return [line]
    first_line = expr_lines[0].lstrip()
    return [f"{line}{first_line}"] + expr_lines[1:]
