"""
rename all names with a unique id.
- to check all name uses are in scope
- so define and uses are linked
"""
import itertools

from collections.abc import Generator, Iterable
from dataclasses import dataclass
from typing import cast

from systemf.elab3.name_gen import check_dups
from systemf.elab3.types.tything import Metas

from .rename_expr import RenameExpr
from .reader_env import ImportRdrElt, ImportSpec, LocalRdrElt, RdrElt, ReaderEnv
from .types import NameGenerator, REPLContext, Module
from .types.ty import Name, BoundTv
from .types.ast import (
    AnnotName, ImportDecl, ModuleDecls,
    RnDataConDecl, RnDataDecl, RnPrimOpDecl, RnPrimTyDecl, RnTermDecl,
)

from systemf.surface.types import (
    SurfaceConstructorInfo,
    SurfaceDataDeclaration,
    SurfaceDeclaration,
    SurfaceImportDeclaration,
    SurfacePrimOpDecl,
    SurfacePrimTypeDecl,
    SurfaceTermDeclaration,
    SurfaceType,
    SurfaceTypeArrow,
    SurfaceTypeForall,
    SurfaceTypeVar,
)

from systemf.utils.location import Location


@dataclass
class RenameResult:
    rn_mod: ModuleDecls


class Rename:
    """
    Assign unique to names lexically.
    """
    ctx: REPLContext
    reader_env: ReaderEnv
    mod_name: str
    name_gen: NameGenerator

    def __init__(self, ctx: REPLContext, reader_env: ReaderEnv, mod_name: str, name_gen: NameGenerator):
        self.ctx = ctx
        self.reader_env = reader_env
        self.mod_name = mod_name
        self.name_gen = name_gen

    @property
    def rename_expr(self):
        """fresh new RenameExpr with local env"""
        return RenameExpr(self.reader_env, self.mod_name, self.name_gen)

    def rename(self, imports: list[SurfaceImportDeclaration], ast: list[SurfaceDeclaration]) -> RenameResult:
        ast_datas, ast_terms, ast_prim_tys, ast_prim_ops = split_ast(ast)
        # imports
        self.do_imports(get_imports(self.mod_name, imports))

        # lhs
        lhs_datas = self.rename_lhs_datas(ast_datas)
        lhs_terms = self.rename_lhs_terms(ast_terms)
        lhs_prim_tys = [self.new_lhs_name(p.name, p.location) for p in ast_prim_tys]
        lhs_prim_ops = [self.new_lhs_name(p.name, p.location) for p in ast_prim_ops]
        lhs_names = itertools.chain(
                [r.name for r in lhs_datas],
                itertools.chain.from_iterable(r.datacons for r in lhs_datas),
                [r.name for r in lhs_terms],
                lhs_prim_tys,
                lhs_prim_ops)
        self.reader_env = self.reader_env + env_from_local_names(lhs_names)

        # rhs
        rn_datas = [self.rename_rhs_data(ld) for ld in lhs_datas]
        rn_terms = [self.rename_rhs_term(lt) for lt in lhs_terms]

        # prims
        rn_prim_tys = [self.rename_prim_ty(p, name) for p, name in zip(ast_prim_tys, lhs_prim_tys)]
        rn_prim_ops = [self.rename_prim_op(p, name) for p, name in zip(ast_prim_ops, lhs_prim_ops)]

        return RenameResult(ModuleDecls(rn_datas, rn_terms, rn_prim_tys, rn_prim_ops))

    def do_imports(self, imports: list[ImportDecl]):
        for imp in imports:
            mod = self.ctx.load(imp.module)
            env = env_from_import_decl(mod, imp)
            self.reader_env = self.reader_env + env

    def rename_lhs_datas(self, datas: list[SurfaceDataDeclaration]) -> list[RnLhsDataResult]:
        def _go(decl: SurfaceDataDeclaration) -> RnLhsDataResult:
            tycon_name = self.new_lhs_name(decl.name, decl.location)
            datacon_names = [
                self.new_lhs_name(con.name, con.location)
                for con in decl.constructors
            ]
            return RnLhsDataResult(tycon_name, datacon_names, decl)
        return [_go(decl) for decl in datas]

    def rename_lhs_terms(self, terms: list[SurfaceTermDeclaration]) -> list[RnLhsTermResult]:
        return [
            RnLhsTermResult(self.new_lhs_name(decl.name, decl.location), decl)
            for decl in terms
        ]

    def rename_rhs_data(self, lhs_res: RnLhsDataResult) -> RnDataDecl:
        var_names = self.new_lhs_names([p.name for p in lhs_res.decl.params], lhs_res.decl.location)
        metas = Metas.create(lhs_res.decl.pragma, lhs_res.decl.docstring, tyvars_to_argdocs(lhs_res.decl.params))
        rn_data = RnDataDecl(
            name=lhs_res.name,
            tyvars=[BoundTv(v) for v in var_names],
            constructors=[],
            metas=metas,
        )

        def _go(con: SurfaceConstructorInfo, con_name: Name) -> RnDataConDecl:
            tys = [
                self.rename_expr.rename_forall_type(var_names, arg)
                for arg in con.args]
            return RnDataConDecl(con_name, rn_data, tys, None)

        for con, con_name in zip(lhs_res.decl.constructors, lhs_res.datacons):
            rn_data.constructors.append(_go(con, con_name))

        return rn_data

    def rename_rhs_term(self, lhs_res: RnLhsTermResult) -> RnTermDecl:
        if lhs_res.decl.type_annotation is None:
            term_ty = None
        else:
            term_ty = self.rename_expr.rename_type(lhs_res.decl.type_annotation)
        term = self.rename_expr.rename_expr(lhs_res.decl.body)
        return RnTermDecl(
            name=AnnotName(lhs_res.name, term_ty) if term_ty else lhs_res.name,
            expr=term,
            metas=None,
        )
    
    def new_lhs_name(self, name: str, loc: Location | None) -> Name:
        """
        Combined NAME_CACHE and NameGenerator
        
        when name is builtin, we return from the cache
        otherwise we generate a new name and put it in the cache so later occ_name lookup finds it.

        NOTE: we only put toplevel LHS names, or more specifically, the exported names, into the cache.
        """
        if (n := self.ctx.name_cache.get(self.mod_name, name)) is not None:
            return n
        n = self.name_gen.new_name(name, loc)
        self.ctx.name_cache.put(n)
        return n

    def new_lhs_names(self, names: list[str], loc: Location | None) -> list[Name]:
        check_dups(names, loc)
        return [self.new_lhs_name(name, loc) for name in names]

    def rename_prim_ty(self, pt: SurfacePrimTypeDecl, name: Name) -> RnPrimTyDecl:
        var_names = self.new_lhs_names([p.name for p in pt.params], pt.location)
        metas = Metas.create(pt.pragma, pt.docstring, tyvars_to_argdocs(pt.params))
        return RnPrimTyDecl(
            name=name,
            tyvars=[BoundTv(v) for v in var_names],
            metas=metas,
        )

    def rename_prim_op(self, op: SurfacePrimOpDecl, name: Name) -> RnPrimOpDecl:
        ty = op.type_annotation
        # FIX: at parser level, make types requried
        if ty is None:
            raise Exception(f"primitive operator {op.name} must have a type annotation at {op.location}")
        metas = Metas.create(op.pragma, op.docstring, funty_to_argdocs(ty))
        return RnPrimOpDecl(
            name=AnnotName(name, self.rename_expr.rename_type(ty)),
            metas=metas,
        )


@dataclass
class RnLhsDataResult:
    name: Name
    datacons: list[Name]
    decl: SurfaceDataDeclaration


@dataclass
class RnLhsTermResult:
    name: Name
    decl: SurfaceTermDeclaration


def split_ast(
    ast: list[SurfaceDeclaration]
) -> tuple[
    list[SurfaceDataDeclaration],
    list[SurfaceTermDeclaration],
    list[SurfacePrimTypeDecl],
    list[SurfacePrimOpDecl],
]:
    datas: list[SurfaceDataDeclaration] = []
    terms: list[SurfaceTermDeclaration] = []
    prim_tys: list[SurfacePrimTypeDecl] = []
    prim_ops: list[SurfacePrimOpDecl] = []
    for decl in ast:
        match decl:
            case SurfaceDataDeclaration():
                datas.append(decl)
            case SurfaceTermDeclaration():
                terms.append(decl)
            case SurfacePrimTypeDecl():
                prim_tys.append(decl)
            case SurfacePrimOpDecl():
                prim_ops.append(decl)
            case _:
                raise Exception(f"unexpected declaration: {decl}")
    return datas, terms, prim_tys, prim_ops


DEFAULT_IMPORTS = [
    ("builtins", ImportDecl(
        module="builtins",
        qualified=False,
        alias=None,
        import_items=None,
        hiding_items=None,
    ))
]


def get_imports(mod: str, imports: list[SurfaceImportDeclaration]) -> list[ImportDecl]:
    return list(itertools.chain(
        [m for n, m in DEFAULT_IMPORTS if n != mod],
        (
            ImportDecl(
                module=decl.module,
                qualified=decl.qualified,
                alias=decl.alias,
                import_items=decl.items,
                hiding_items=[],  # TODO: fix surface to support hiding items
            ) for decl in imports
        )
    ))


def env_from_import_decl(mod: Module, decl: ImportDecl) -> ReaderEnv:
    spec = ImportSpec.from_decl(decl)
    if decl.import_items:
        imports = set(decl.import_items)
        items = [item for item in mod.exports if item.surface in imports]
    else:
        hidings = set(decl.hiding_items or [])
        items = [item for item in mod.exports if item.surface not in hidings]
    return ReaderEnv.from_elts([
        cast(RdrElt, ImportRdrElt(item, [spec]))
        for item in items
    ])


def env_from_local_names(names: Iterable[Name]) -> ReaderEnv:
    return ReaderEnv.from_elts([
        LocalRdrElt(name=name)
        for name in names
    ])


def funty_to_argdocs(ty: SurfaceType) -> list[str | None]:
    """
    Extract argument documentation from a function type.
    """
    def _go(ty: SurfaceType) -> Generator[str | None, None, None]:
        match ty:
            case SurfaceTypeArrow(arg=arg_ty, ret=res_ty):
                yield arg_ty.docstring
                yield from _go(res_ty)
            case SurfaceTypeForall(body=body):
                yield from _go(body)
            case ty:
                yield ty.docstring
    arg_docs = list(_go(ty))
    return arg_docs


def tyvars_to_argdocs(tyvars: list[SurfaceTypeVar]) -> list[str | None]:
    """
    Extract argument documentation from a list of type variables.
    """
    return [tv.docstring for tv in tyvars]


def datacon_to_argdocs(con: SurfaceConstructorInfo) -> list[str | None]:
    """
    Extract argument documentation from a data constructor.
    """
    return [arg.docstring for arg in con.args]
