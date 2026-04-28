# GHC Compiler Directory Organization Guide

## Top-Level Structure

```
compiler/
├── GHC/                    # Main compiler implementation (Haskell modules)
├── Language/               # Language-specific utilities
├── cbits/                  # C FFI bindings
├── jsbits/                 # JavaScript backend bits
├── GHC.hs                  # Top-level module entry point
├── Setup.hs                # Cabal setup script
├── ghc.cabal.in            # Cabal package configuration template
├── CodeGen.Platform.h      # Platform-specific code generation header
├── Unique.h                # Unique ID generation header
├── LICENSE                 # License file
└── [notes files]           # Flattening and profiling documentation
```

## GHC/ Subdirectory - The Core Compiler

The main compiler implementation is organized into functional phases and subsystems:

### Phase 1: Parsing

```
GHC/Parser/
├── Parser.y                # Happy grammar file (generates lexer/parser)
├── Lexer.x                 # Alex lexer specification
├── Types.hs                # Parser type definitions
├── Header.hs               # Parser header utilities
└── [various utilities]

GHC/Hs/                      # Haskell syntax tree representation
├── Decls.hs                # Declaration AST nodes
├── Expr.hs                 # Expression AST nodes
├── Pat.hs                  # Pattern AST nodes
├── Type.hs                 # Type AST nodes
├── Binds.hs                # Binding AST nodes
├── Module.hs               # Module structure
└── [extension tracking]
```

### Phase 2: Renaming

```
GHC/Rename/
├── Rename.hs               # Main renaming driver
├── Env.hs                  # Renaming environment
├── Expr.hs                 # Expression renaming
├── Pat.hs                  # Pattern renaming
├── Type.hs                 # Type renaming
├── Bind.hs                 # Binding renaming
├── Module.hs               # Module renaming
├── Fixity.hs               # Fixity resolution
├── HsType.hs               # Type syntax handling
└── Uniq.hs                 # Unique renaming
```

### Phase 3: Type Checking (Tc/)

This is the largest subsystem, implementing bidirectional type inference:

```
GHC/Tc/
├── Module.hs               # Module-level type checking entry point
├── TyCl/                   # Type and class declarations
│   ├── TyCl.hs            # Main type checking driver
│   ├── Instance.hs        # Instance declaration handling
│   ├── Class.hs           # Type class handling
│   ├── PatSyn.hs          # Pattern synonym handling
│   ├── Build.hs           # Type/class building utilities
│   └── Utils.hs
│
├── Gen/                    # Code generation for expressions/patterns
│   ├── Expr.hs            # Expression type checking (bidirectional)
│   ├── Match.hs           # Pattern matching type checking
│   ├── Pat.hs             # Pattern type checking
│   ├── Bind.hs            # Binding type checking
│   ├── App.hs             # Application type checking (Quick Look)
│   ├── Head.hs            # Head expression inference
│   ├── HsType.hs          # Type signature checking
│   ├── Splice.hs          # Template Haskell splices
│   ├── Arrow.hs           # Arrow notation
│   ├── Do.hs              # Do-notation desugaring
│   ├── Default.hs         # Default type handling
│   ├── Foreign.hs         # FFI type checking
│   ├── Annotation.hs      # Annotation checking
│   └── Sig.hs             # Signature type checking
│
├── Instance/              # Instance resolution and constraint handling
│   ├── Class.hs           # Type class instance handling
│   ├── Family.hs          # Family instance handling
│   ├── FunDeps.hs         # Functional dependency handling
│   └── Typeable.hs        # Typeable instance generation
│
├── Solver/                # Constraint solving engine
│   ├── Solve.hs           # Main constraint solver
│   ├── Monad.hs           # Solver monad
│   ├── InertSet.hs        # Inert constraint set
│   ├── Dict.hs            # Dictionary constraint solving
│   ├── Equality.hs        # Equality constraint solving
│   ├── Irred.hs           # Irreducible constraints
│   ├── FunDeps.hs         # Functional dependencies
│   ├── Rewrite.hs         # Constraint rewriting
│   ├── Default.hs         # Default resolution
│   └── Types.hs           # Solver type definitions
│
├── Utils/                 # Type checking utilities
│   ├── TcMType.hs         # ExpType and inference operations
│   ├── TcType.hs          # Type checking types and operations
│   ├── Unify.hs           # Unification algorithm
│   ├── Monad.hs           # Type checking monad (TcM)
│   ├── Env.hs             # Type checking environment
│   ├── Zonk.hs            # Zonking (substitution application)
│   └── [various utilities]
│
├── Deriv/                 # Deriving mechanism
│   ├── Deriv.hs           # Main deriving driver
│   ├── Infer.hs           # Constraint inference for derived instances
│   ├── Generate.hs        # Code generation for derived instances
│   ├── Generics.hs        # Generics deriving
│   ├── Functor.hs         # Functor/Foldable/Traversable deriving
│   └── Utils.hs
│
├── Errors/                # Error reporting
│   ├── Errors.hs          # Main error handling
│   ├── Types.hs           # Error type definitions
│   ├── Ppr.hs             # Error pretty-printing
│   ├── Hole/              # Hole error handling
│   └── Types/
│       └── PromotionErr.hs
│
├── Plugin.hs              # Type checking plugin interface
└── [other modules]
```

**Key File: `GHC/Tc/Gen/Expr.hs`**
- Main expression type checker with `tcExpr` function
- Implements bidirectional type inference
- Entry points: `tcCheckPolyExpr`, `tcInferRho`, `tcCheckMonoExpr`

**Key File: `GHC/Tc/Utils/TcType.hs`**
- Defines `ExpType` data structure
- Central to bidirectional inference system

**Key File: `GHC/Tc/Utils/TcMType.hs`**
- `ExpType` manipulation functions
- Hole creation and filling operations

### Phase 4: Desugaring to Core

```
GHC/HsToCore/
├── HsToCore.hs            # Main desugaring driver
├── Expr.hs                # Expression desugaring
├── Match.hs               # Pattern match compilation
├── Binds.hs               # Binding desugaring
├── Arrows.hs              # Arrow notation desugaring
├── Do.hs                  # Do-notation desugaring
├── GuardedRHS.hs          # Guarded RHS handling
├── ListComp.hs            # List comprehension desugaring
├── Monad.hs               # Monad-related desugaring
└── [other utilities]

GHC/CoreToIface.hs         # Core to interface conversion
GHC/IfaceToCore.hs         # Interface to core conversion
```

### Phase 5: Core Representation

```
GHC/Core/
├── Core.hs                # Core language definition
├── Expr.hs                # Core expressions
├── Type.hs                # Core types
├── Coercion.hs            # Type coercions
├── Opt/                   # Core optimizations
│   ├── Opt.hs
│   ├── OccurAnal.hs       # Occurrence analysis
│   ├── Simplify.hs        # Simplifier optimization
│   ├── SpecConstr.hs      # Specialization
│   └── [other passes]
├── Rules.hs               # Rewrite rules
└── [various utilities]

GHC/Types/                 # Type system definitions
├── Id.hs                  # Identifier representation
├── Var.hs                 # Variable representation
├── TyCoRep.hs             # Type and coercion representation
├── Kind.hs                # Kind checking
├── Type.hs                # Type manipulation
├── Coercion.hs            # Coercion manipulation
└── [other type utilities]
```

### Phase 6: STG Conversion

```
GHC/Stg/
├── Stg.hs                 # STG language definition
├── Syntax.hs              # STG syntax
├── Lift.hs                # Lambda lifting
├── Unarise.hs             # Unarisation
└── [other STG utilities]

GHC/CoreToStg.hs           # Core to STG conversion
```

### Phase 7: Code Generation

```
GHC/StgToCmm.hs            # STG to C-- conversion

GHC/Cmm/                   # C-- intermediate language
├── Cmm.hs                 # C-- definition
├── Expr.hs                # C-- expressions
├── Monad.hs               # C-- generation monad
├── Opt.hs                 # C-- optimizations
└── [utilities]

GHC/CmmToAsm/              # C-- to native assembly
├── Instr.hs               # Instruction definitions
├── Ppr.hs                 # Assembly pretty-printing
├── RegAlloc.hs            # Register allocation
├── Dwarf.hs               # DWARF debug info
└── [platform-specific]

GHC/CmmToLlvm/             # C-- to LLVM IR
├── LLVM.hs
├── Ppr.hs
└── [utilities]

GHC/StgToJS/               # STG to JavaScript (for GHCJS)
└── [JavaScript backend]

GHC/StgToByteCode.hs       # STG to bytecode (for GHCi)

GHC/Llvm/                  # LLVM utilities
└── [LLVM support]
```

### Backend Support

```
GHC/CmmToAsm/              # Native code generation
GHC/CmmToLlvm/             # LLVM code generation
GHC/StgToJS/               # JavaScript code generation
GHC/Wasm/                  # WebAssembly support
GHC/JS/                    # JavaScript utilities
```

### Support & Infrastructure

```
GHC/Driver/
├── Main.hs                # Main entry point
├── Phases.hs              # Compilation phases
├── Pipeline.hs            # Compilation pipeline
├── Session.hs             # Compiler session management
├── Config.hs              # Configuration
├── Flags.hs               # Compiler flags
└── [driver utilities]

GHC/Unit/
├── Module.hs              # Module definitions
├── Home.hs                # Home package handling
├── Env.hs                 # Unit environment
├── State.hs               # Package state
└── [unit system utilities]

GHC/Iface/                 # Interface (.hi) file handling
├── Syntax.hs              # Interface syntax
├── Load.hs                # Loading interface files
├── Make.hs                # Creating interface files
└── [interface utilities]

GHC/Builtin/               # Built-in definitions
├── Names.hs               # Built-in names
├── Types.hs               # Built-in types
├── PrimOps.hs             # Primitive operations
├── Rules.hs               # Built-in rules
└── [built-in utilities]

GHC/Data/                  # Data structures and utilities
├── Graph.hs               # Graph algorithms
├── Bag.hs                 # Bag data structure
├── UnionFind.hs           # Union-Find
├── Trie.hs                # Trie data structure
└── [various utilities]

GHC/Utils/                 # General utilities
├── Misc.hs                # Miscellaneous utilities
├── Outputable.hs          # Pretty-printing infrastructure
├── Panic.hs               # Error handling
├── Fingerprint.hs         # Fingerprinting
└── [general utilities]

GHC/Runtime/               # Runtime system
├── Heap.hs                # Heap representation
├── Interpreter.hs         # Bytecode interpreter
└── [runtime utilities]

GHC/Linker/                # Linker integration
├── Loader.hs              # Object code loading
├── DynLinker.hs           # Dynamic linking
└── [linker utilities]

GHC/SysTools/              # System tools interface
├── Elf.hs                 # ELF file handling
├── FileClean.hs           # File cleanup
└── [system tool utilities]

GHC/Settings/              # Compiler settings
├── Config.hs              # Configuration
├── IO.hs                  # Settings I/O
└── [settings utilities]

GHC/Platform/              # Platform-specific code
├── Host.hs                # Host platform
├── Target.hs              # Target platform
└── [platform utilities]

GHC/Prelude/               # Prelude-like definitions
└── [prelude utilities]

GHC/ByteCode/              # Bytecode interpreter
├── Interpreter.hs
├── Assembler.hs
└── [bytecode utilities]
```

## Language/ Subdirectory

```
Language/Haskell/
├── Syntax/                # Haskell syntax definitions
├── [...other utilities]
```

## cbits/ and jsbits/

```
cbits/                      # C code for FFI
├── Adler32.c              # Adler32 checksums
├── Base16.c               # Base16 encoding
└── [other C utilities]

jsbits/                     # JavaScript for JS backend
└── [JavaScript utilities]
```

## Key Architecture Patterns

### 1. Phase Separation
Each compilation phase is cleanly separated:
- **Input**: Previous phase's output
- **Processing**: Phase-specific logic
- **Output**: Next phase's input

### 2. Monad-Based Computation
Most phases use custom monads:
- `TcM` (type checking monad) in Tc/
- `CmmM` (C-- monad) in Cmm/
- `SolverM` (constraint solver monad) in Tc/Solver/

### 3. AST Representation
Each phase has its own AST:
- `HsExpr` (Haskell source)
- `CoreExpr` (Core)
- `StgExpr` (STG)
- `CmmExpr` (C--)
- Platform-specific instructions

### 4. Environment Tracking
Each phase maintains an environment:
- `TcGblEnv`, `TcLclEnv` (type checking)
- `DynFlags` (compiler flags)
- `Module`, `Package` (module/package info)

## Compilation Flow

```
Source Code (.hs)
    ↓
Parser (GHC/Parser/) → HsExpr
    ↓
Renamer (GHC/Rename/) → RenamedExpr
    ↓
Type Checker (GHC/Tc/) → TcExpr
    ↓
Desugarer (GHC/HsToCore/) → CoreExpr
    ↓
Core Optimizer (GHC/Core/Opt/) → OptimizedCoreExpr
    ↓
STG Converter (GHC/CoreToStg/) → StgExpr
    ↓
Code Generator (GHC/StgToCmm/) → CmmExpr
    ↓
Assembly Generator (GHC/CmmToAsm/) → NativeCode
    ↓
Linker (GHC/Linker/) → Executable
```

## Important Design Principles

1. **Separation of Concerns**: Each phase handles one aspect (parsing, renaming, type checking, etc.)
2. **Immutable Data**: Most data structures are immutable (except mutable refs in TcM)
3. **Error Reporting**: Centralized error handling in GHC/Tc/Errors/
4. **Extensibility**: Plugin system in GHC/Tc/Plugin.hs
5. **Performance**: Quick Look optimization, occurrence analysis, simplification passes

## Key Entry Points

- **`GHC/Driver/Main.hs`**: Compilation driver
- **`GHC/Tc/Module.hs`**: Module-level type checking
- **`GHC/Tc/Gen/Expr.hs`**: Expression type checking (bidirectional)
- **`GHC/HsToCore/HsToCore.hs`**: Desugaring entry point
- **`GHC/StgToCmm.hs`**: Code generation entry point

## Summary

The GHC compiler is organized as a pipeline of well-separated phases, each with:
- Clear input/output types
- Dedicated modules
- Phase-specific operations

The type checking phase (GHC/Tc/) is particularly complex, implementing:
- **Bidirectional type inference** via ExpType
- **Constraint solving** via the constraint solver
- **Instance resolution** for overloading
- **Deriving mechanism** for automatic instance generation