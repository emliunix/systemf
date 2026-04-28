"""
typecheck module
"""

from systemf.elab3.types.tc import NonRecGroup, RecGroup
from .typecheck_expr import TypeChecker, ds_binding

from .types import NameGenerator, REPLContext, Name, Ty
from .types.ast import Binding, ModuleDecls, RnDataConDecl, RnDataDecl, RnPrimOpDecl, RnPrimTyDecl, RnTermDecl
from .types.core import CoreTm, CoreLet, NonRec, Rec, C
from .types.ty import Id, zonk_type
from .types.tything import APrimTy, AnId, TypeEnv, ATyCon, ACon
from systemf.elab3.types import core


class Typecheck:
    mod_name: str
    ctx: REPLContext
    name_gen: NameGenerator
    type_env: TypeEnv


    def __init__(self, mod_name: str, ctx: REPLContext, name_gen: NameGenerator, type_env: TypeEnv | None = None):
        self.mod_name = mod_name
        self.ctx = ctx
        self.name_gen = name_gen
        self.type_env = type_env if type_env is not None else {}
    
    @property
    def typecheck_expr(self):
        return TypeChecker(
            self.ctx,
            self.mod_name,
            self.name_gen,
            self.type_env
        )

    def typecheck(self, mod: ModuleDecls) -> tuple[TypeEnv, list[core.Binding]]:
        ty_env = self.tc_datas(mod.data_decls)
        ty_env.update(self.tc_prims(mod.prim_ty_decls, mod.prim_op_decls))

        # update for tc_valbinds
        self.type_env.update(ty_env)
        bindings = self.tc_valbinds(mod.term_decls)

        def _ids_binding(binding: core.Binding) -> list[Id]:
            match binding:
                case NonRec(bndr, _):
                    return [bndr]
                case Rec(bindings):
                    return [bndr for bndr, _ in bindings]

        ty_env.update((id.name, AnId.create(id))
                      for binding in bindings
                      for id in _ids_binding(binding))
        return ty_env, bindings

    def tc_datas(self, data_decls: list[RnDataDecl]) -> TypeEnv:
        """
        Simply populate type env with data types.
        """

        env: TypeEnv = {}

        def _acon(tag: int, con: RnDataConDecl) -> ACon:
            return ACon(con.name, tag, len(con.fields), con.fields, con.tycon.name, metas=con.metas)
        for data_decl in data_decls:
            cons = [_acon(i, con) for i, con in enumerate(data_decl.constructors)]
            env[data_decl.name] = ATyCon(data_decl.name, data_decl.tyvars, cons, metas=data_decl.metas)
            for con in cons:
                env[con.name] = con
        return env

    def tc_prims(self, ptys: list[RnPrimTyDecl], pops: list[RnPrimOpDecl]) -> TypeEnv:
        env: TypeEnv = {}
        for ty in ptys:
            env[ty.name] = APrimTy(ty.name, ty.tyvars, metas=ty.metas)
        for op in pops:
            name, ty = op.name.name, op.name.type_ann
            env[name] = AnId.create(Id(name, ty), is_prim=True, metas=op.metas)
        return env

    def tc_valbinds(self, valbinds: list[RnTermDecl]) -> list[core.Binding]:
        groups, _ = self.typecheck_expr.bindings([Binding(b.name, b.expr) for b in valbinds], lambda: None)
        bs = [
            ds_binding(group)
            for group in groups
        ]
        return [zonk_binding(b) for b in bs]
    

def zonk_binding(binding: core.Binding) -> core.Binding:
    match binding:
        case NonRec(bndr, expr):
            return NonRec(Id(bndr.name, zonk_type(bndr.ty)), expr)
        case Rec(bindings):
            new_bindings = [(Id(bndr.name, zonk_type(bndr.ty)), expr) for bndr, expr in bindings]
            return Rec(new_bindings)
