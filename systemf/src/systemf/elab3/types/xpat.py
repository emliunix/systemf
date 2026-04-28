
from dataclasses import dataclass

from .ty import Id, Lit, Name, Ty
from .wrapper import Wrapper


@dataclass
class XPatLit:
    lit: Lit


@dataclass
class XPatCon:
    con: Name
    args: list[XPat]
    arg_tys: list[Ty]


@dataclass
class XPatVar:
    bndr: Id


@dataclass
class XPatCo:
    """
    Internal node for wrapper
    """
    co: Wrapper
    res_ty: Ty
    pat: XPat


@dataclass
class XPatWild:
    pass


type XPat = XPatCo | XPatLit | XPatCon | XPatVar | XPatWild
