"""Pretty printer for TyThing type environment entries.

Produces source-accurate syntax matching the parser grammar:

    prim_op name :: forall a. a -- ^ arg doc
        -> a -- ^ result doc
    name :: Type
    prim_type name a b c
    data Name a b c
        = Con x -- ^ doc for x
            y z
        | Con2

Docstrings: split on newline, one ``-- |`` per line.
Arg docs: inline ``-- ^`` after each argument, multi-line with indented ``->``.
Every line ends with a newline.
"""

from .types.ty import Ty, TyForall, TyFun, TyVar, _ty_repr
from .types.tything import ACon, APrimTy, ATyCon, AnId, Metas, TyThing


def _ty_str(ty: Ty) -> str:
    return _ty_repr(ty, 0)


def _ty_str_arg(ty: Ty) -> str:
    return _ty_repr(ty, 2)


def _peel_forall(ty: Ty) -> tuple[list[list[str]], Ty]:
    varss: list[list[str]] = []
    rest = ty
    while isinstance(rest, TyForall):
        varss.append([_ty_repr(v, 0) for v in rest.vars])
        rest = rest.body
    return varss, rest


def _peel_fun(ty: Ty) -> tuple[list[Ty], Ty]:
    args: list[Ty] = []
    rest = ty
    while isinstance(rest, TyFun):
        args.append(rest.arg)
        rest = rest.result
    return args, rest


def _pp_pragma_lines(metas: Metas | None) -> list[str]:
    if metas is None or not metas.pragma:
        return []
    return [f"{{-# {k} {v} #-}}" for k, v in metas.pragma.items()]


def _pp_doc_lines(doc: str | None) -> list[str]:
    if not doc:
        return []
    return [f"-- | {line}" for line in doc.split("\n")]


def _has_arg_docs(metas: Metas | None) -> bool:
    return metas is not None and any(d is not None for d in metas.arg_docs)


def _forall_prefix(varss: list[list[str]]) -> str:
    if not varss:
        return ""
    parts = " ".join(v for vs in varss for v in vs)
    return f"forall {parts}. "


# =============================================================================
# Public API
# =============================================================================


def pp_tything(thing: TyThing) -> str:
    match thing:
        case AnId(name=name, id=id, is_prim=is_prim, metas=metas):
            return _pp_binding(name.surface, id.ty, is_prim, metas)
        case ATyCon(name=name, tyvars=tyvars, constructors=cons, metas=metas):
            return _pp_data(name.surface, tyvars, cons, metas)
        case ACon(name=name, field_types=fields, metas=metas):
            return _pp_acon(name.surface, fields, metas)
        case APrimTy(name=name, tyvars=tyvars, metas=metas):
            return _pp_prim_type(name.surface, tyvars, metas)
        case _:
            return f"<unknown TyThing: {type(thing).__name__}>\n"


# =============================================================================
# Private helpers
# =============================================================================


def _pp_binding(name: str, ty: Ty, is_prim: bool, metas: Metas | None) -> str:
    lines: list[str] = []
    lines.extend(_pp_doc_lines(metas.doc if metas else None))
    lines.extend(_pp_pragma_lines(metas))

    kw = "prim_op " if is_prim else ""
    prefix = f"{kw}{name} :: "

    varss, body = _peel_forall(ty)
    forall_str = _forall_prefix(varss)
    args, result = _peel_fun(body)

    arg_docs = (metas.arg_docs if metas else None) or []
    all_tys = args + [result]

    if not _has_arg_docs(metas):
        lines.append(f"{prefix}{_ty_str(ty)}")
    else:
        first_ty, *rest_tys = all_tys
        first_doc = arg_docs[0] if arg_docs else None
        first_s = _ty_str_arg(first_ty)
        first_doc_s = f" -- ^ {first_doc}" if first_doc else ""
        lines.append(f"{prefix}{forall_str}{first_s}{first_doc_s}")

        for i, arg_ty in enumerate(rest_tys, start=1):
            doc = arg_docs[i] if i < len(arg_docs) else None
            arg_s = _ty_str_arg(arg_ty)
            doc_s = f" -- ^ {doc}" if doc else ""
            lines.append(f"    -> {arg_s}{doc_s}")

    return "\n".join(lines) + "\n"


def _pp_data(name: str, tyvars: list[TyVar], constructors: list[ACon], metas: Metas | None) -> str:
    lines: list[str] = []
    lines.extend(_pp_doc_lines(metas.doc if metas else None))
    lines.extend(_pp_pragma_lines(metas))

    arg_docs = (metas.arg_docs if metas else None) or []

    if not tyvars:
        header = f"data {name}"
    elif not _has_arg_docs(metas):
        var_str = " ".join(_ty_repr(v, 0) for v in tyvars)
        header = f"data {name} {var_str}"
    else:
        first_var = tyvars[0]
        first_doc = arg_docs[0] if arg_docs else None
        first_s = _ty_repr(first_var, 0)
        first_doc_s = f" -- ^ {first_doc}" if first_doc else ""
        lines.append(f"data {name} {first_s}{first_doc_s}")

        for i, tv in enumerate(tyvars[1:], start=1):
            doc = arg_docs[i] if i < len(arg_docs) else None
            var_s = _ty_repr(tv, 0)
            doc_s = f" -- ^ {doc}" if doc else ""
            lines.append(f"    {var_s}{doc_s}")

        header = None

    if not constructors:
        if header:
            lines.append(header)
        return "\n".join(lines) + "\n"

    if header:
        lines.append(header)

    # Constructors
    first_con_lines = _pp_acon_inline(constructors[0])
    lines.append(f"    = {first_con_lines[0]}")
    for cl in first_con_lines[1:]:
        lines.append(f"      {cl}")

    for con in constructors[1:]:
        con_lines = _pp_acon_inline(con)
        lines.append(f"    | {con_lines[0]}")
        for cl in con_lines[1:]:
            lines.append(f"      {cl}")

    return "\n".join(lines) + "\n"


def _pp_acon_inline(con: ACon) -> list[str]:
    """Format a data constructor and its fields, returning list of lines."""
    lines: list[str] = []
    metas = con.metas
    lines.extend(_pp_doc_lines(metas.doc if metas else None))
    lines.extend(_pp_pragma_lines(metas))

    fields = con.field_types
    arg_docs = (metas.arg_docs if metas else None) or []

    if not fields or not _has_arg_docs(metas):
        parts = [con.name.surface]
        for ft in fields:
            parts.append(_ty_str_arg(ft))
        lines.append(" ".join(parts))
    else:
        first_field = fields[0]
        first_doc = arg_docs[0] if arg_docs else None
        first_s = _ty_str_arg(first_field)
        first_doc_s = f" -- ^ {first_doc}" if first_doc else ""
        lines.append(f"{con.name.surface} {first_s}{first_doc_s}")

        for i, ft in enumerate(fields[1:], start=1):
            doc = arg_docs[i] if i < len(arg_docs) else None
            field_s = _ty_str_arg(ft)
            doc_s = f" -- ^ {doc}" if doc else ""
            lines.append(f"    {field_s}{doc_s}")

    return lines


def _pp_acon(name: str, fields: list[Ty], metas: Metas | None) -> str:
    lines: list[str] = []
    lines.extend(_pp_doc_lines(metas.doc if metas else None))
    lines.extend(_pp_pragma_lines(metas))

    arg_docs = (metas.arg_docs if metas else None) or []

    if not fields or not _has_arg_docs(metas):
        parts = [name]
        for f in fields:
            parts.append(_ty_str_arg(f))
        lines.append(" ".join(parts))
    else:
        first_field = fields[0]
        first_doc = arg_docs[0] if arg_docs else None
        first_s = _ty_str_arg(first_field)
        first_doc_s = f" -- ^ {first_doc}" if first_doc else ""
        lines.append(f"{name} {first_s}{first_doc_s}")

        for i, f in enumerate(fields[1:], start=1):
            doc = arg_docs[i] if i < len(arg_docs) else None
            field_s = _ty_str_arg(f)
            doc_s = f" -- ^ {doc}" if doc else ""
            lines.append(f"    {field_s}{doc_s}")

    return "\n".join(lines) + "\n"


def _pp_prim_type(name: str, tyvars: list[TyVar], metas: Metas | None) -> str:
    lines: list[str] = []
    lines.extend(_pp_doc_lines(metas.doc if metas else None))
    lines.extend(_pp_pragma_lines(metas))

    arg_docs = (metas.arg_docs if metas else None) or []

    if not tyvars:
        lines.append(f"prim_type {name}")
    elif not _has_arg_docs(metas):
        var_str = " ".join(_ty_repr(v, 0) for v in tyvars)
        lines.append(f"prim_type {name} {var_str}")
    else:
        first_var = tyvars[0]
        first_doc = arg_docs[0] if arg_docs else None
        first_s = _ty_repr(first_var, 0)
        first_doc_s = f" -- ^ {first_doc}" if first_doc else ""
        lines.append(f"prim_type {name} {first_s}{first_doc_s}")

        for i, tv in enumerate(tyvars[1:], start=1):
            doc = arg_docs[i] if i < len(arg_docs) else None
            var_s = _ty_repr(tv, 0)
            doc_s = f" -- ^ {doc}" if doc else ""
            lines.append(f"    {var_s}{doc_s}")

    return "\n".join(lines) + "\n"
