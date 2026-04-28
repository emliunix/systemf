from systemf.elab3.name_gen import NameGeneratorImpl
from systemf.elab3.reader_env import ReaderEnv
from systemf.elab3.rename import Rename
from systemf.elab3.typecheck import Typecheck
from systemf.elab3.types import Module, REPLContext

from systemf.elab3.types.ty import Name
from systemf.elab3.types.tything import TyThing
from systemf.surface.parser import parse_program
from systemf.surface.types import SurfaceDeclaration, SurfaceImportDeclaration

type Code = str | tuple[list[SurfaceImportDeclaration], list[SurfaceDeclaration]]


def execute(ctx: REPLContext, mod_name: str, file_path: str, code: Code,
            reader_env: ReaderEnv | None = None,
            type_env: dict[Name, TyThing] | None = None
            ) -> Module:
    if isinstance(code, str):
        imports, decls = parse_program(code, file_path)
    else:
        imports, decls = code

    # 1. Parse
    if reader_env is None:
        reader_env = ReaderEnv.empty()

    name_gen = NameGeneratorImpl(mod_name, ctx.uniq)

    # 2. rename

    rename = Rename(ctx, reader_env, mod_name, name_gen)
    res = rename.rename(imports, decls)

    # 3. Typecheck
    typecheck = Typecheck(mod_name, ctx, name_gen, type_env)
    type_env, bindings = typecheck.typecheck(res.rn_mod)

    return Module(
        name=mod_name,
        tythings=list(type_env.items()),
        bindings=bindings,
        exports=list(type_env.keys()),
        _tythings_map=type_env,
        source_path=file_path
    )
