from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import cast

from systemf.elab3.reader_env import QualName
from systemf.elab3.repl_session import REPLSession
from systemf.elab3.types.ty import LitString, Name, Ty, TyConApp, TyForall, TyFun, TyPrim, TyString
from systemf.elab3.types.tything import AnId
from systemf.elab3.types.val import VData, VLit, VPrim, Val


@dataclass
class MainInfo:
    """
    Matches against the main function to extract various info.
    """
    main: AnId
    str_ty: tuple[int, Ty] | None
    prompt_ty: tuple[int, Ty] | None
    res_ty: Ty
    res_inner_ty: Ty

    @staticmethod
    def from_session(repl: REPLSession) -> MainInfo:
        main = repl.lookup(repl.resolve_name(QualName("main", "main")))
        if not isinstance(main, AnId):
            raise Exception("main.main is not an Id")
        return MainInfo.from_id(main)

    @staticmethod
    def from_id(main: AnId) -> MainInfo:
        
        prompt_ty = None
        str_ty = None
        
        arg_tys, res_ty = split_fun(main.id.ty)
        for i, arg_ty in enumerate(arg_tys):
            match arg_ty:
                case TyConApp(Name(mod="bub", surface="Steering"), []):
                    if prompt_ty is not None:
                        raise Exception("Multiple Steering arguments not supported")
                    prompt_ty = (i, arg_ty)
                case TyString():
                    if str_ty is not None:
                        raise Exception("Multiple String arguments not supported")
                    str_ty = (i, arg_ty)
                case _:
                    raise Exception(f"Unexpected argument type for main.main: {arg_ty}")
        match match_tycon_app(res_ty, "bub", "LLM"):
            case [inner_ty]:
                res_inner_ty = inner_ty
            case _:
                raise Exception(f"Unexpected result type for main.main: {res_ty}")
                
        return MainInfo(main, str_ty, prompt_ty, res_ty, res_inner_ty)


@dataclass
class MatchLLMResult:
    """
    Matches against a LLM function to extract various info we need
    """
    orig_arg_num: int
    tape_idx: int | None
    steering_idx: int | None
    arg_tys: list[Ty]
    arg_idxs: list[int]
    is_llm_res: bool
    res_ty: Ty

    @staticmethod
    def from_ty(ty: Ty) -> MatchLLMResult:
        raw_arg_tys, raw_res_ty = split_fun(ty)
        arg_tys = []
        arg_idxs = []
        is_llm_res = False
        res_ty = raw_res_ty
        tape_idx = None
        steering_idx = None
        # split args and pick out the Tape argument if it exists
        for i, arg_ty in enumerate(raw_arg_tys):
            match arg_ty:
                case TyConApp(Name(mod="bub", surface="Tape"), []):
                    if tape_idx is not None:
                        raise Exception("Multiple Tape arguments not supported")
                    tape_idx = i
                case TyConApp(Name(mod="bub", surface="Steering"), []):
                    if steering_idx is not None:
                        raise Exception("Multiple Steering arguments not supported")
                    steering_idx = i
                case _:
                    arg_idxs.append(i)
                    arg_tys.append(arg_ty)

        # check if the result is an LLM result and if so, unwrap it
        match match_tycon_app(res_ty, "bub", "LLM"):
            case [inner_ty]:
                is_llm_res = True
                res_ty = inner_ty
        
        return MatchLLMResult(
            orig_arg_num=len(raw_arg_tys),
            tape_idx=tape_idx,
            steering_idx=steering_idx,
            arg_tys=arg_tys,
            arg_idxs=arg_idxs,
            is_llm_res=is_llm_res,
            res_ty=res_ty,
        )
    

def match_tycon_app(ty: Ty, mod: str, surface: str) -> list[Ty] | None:
    match ty:
        case TyConApp(name=Name(mod=mod_, surface=surface_), args=args) if mod_ == mod and surface_ == surface:
            return args
        case _:
            return None


def split_fun(ty: Ty) -> tuple[list[Ty], Ty]:
    def _go(ty: Ty) -> Generator[Ty, None, None]:
        match ty:
            case TyFun(arg, res):
                yield arg
                yield from _go(res)
            case TyForall(_, body):
                yield from _go(body)
            case _:
                yield ty
    tys = list(_go(ty))
    return tys[:-1], tys[-1]


def prim_val[T](val: Val) -> T:
    match val:
        case VPrim(s):
            return cast(T, s)
        case v:
            raise Exception(f"Expected primitive string value, got: {v}")
        

def str_val(val: Val) -> str:
    match val:
        case VLit(LitString(s)):
            return s
        case v:
            raise Exception(f"Expected literal string value, got: {v}")


def maybe_val[T](inside: Callable[[Val], T], val: Val) -> T | None:
    match val:
        case VData(0, []):
            return None
        case VData(1, [inner]):
            return inside(inner)
        case v:
            raise Exception(f"Expected Maybe value, got: {v}")
