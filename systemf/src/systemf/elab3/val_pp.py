
from .types.protocols import TyLookup
from .types.ty import Ty, TyConApp, subst_ty
from .types.val import VPrim, Val, Trap, VPartial, VData, VClosure, VLit
from .core_extra import lookup_data_con_by_tag


def pp_val(ctx: TyLookup, val: Val, ty: Ty) -> str:
    """Pretty print a value using the evaluator's machinery."""
    # print(val, ty)
    def _pp(val: Val, ty: Ty) -> str:
        match val, ty:
            case VData(tag=tag, vals=args), TyConApp(name=con, args=arg_tys):
                tycon, dcon, _ = lookup_data_con_by_tag(ctx, con, tag)
                dcon_field_tys = [subst_ty(tycon.tyvars, arg_tys, ty) for ty in dcon.field_types]
                vals_str = " ".join(_pp(arg, ty) for ty, arg in zip(dcon_field_tys, args))
                return f"{dcon.name.surface} {vals_str}".strip()
            case VLit(lit=lit), _:
                return f"{lit.v!r}"
            case VPartial(name=name, arity=arity), _:
                return f"<func {name} {arity}>"
            case VClosure(), _:
                return "<closure>"
            case VPrim(), _:
                return "<prim>"
            case Trap(v=None), _:
                return "<unfilled trap>"
            case Trap(v=v), _ if v is not None:
                return _pp(v, ty)
            case _, _: return "<unknown>"
    return f"{_pp(val, ty)} :: {ty}"
