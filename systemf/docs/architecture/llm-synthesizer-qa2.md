# System F LLM Synthesizer Design - Follow-up Q&A

**Status**: Draft - Round 2 Answers

---

## 1. Registry & Context Lifecycle

### Q1.1: Registry cleanup timing?

**Answer**: **Session end**. Registry is tied to Evaluator lifecycle:

```python
class Evaluator:
    def __init__(self):
        self.synthesis_registry: dict[str, SynthesisContext] = {}
        # Registry lives as long as evaluator
    
    def shutdown(self):
        """Called when session ends."""
        self.synthesis_registry.clear()
```

No explicit per-function removal - redefinition overwrites, session end clears all.

### Q1.2: Memory management on redefinition?

**Answer**: **Overwrite in place** - old context eligible for GC:

```python
def register_llm_function(self, name: str, context: SynthesisContext):
    """Redefinition overwrites, old context GC'd."""
    self.synthesis_registry[name] = context  # Old value dropped
```

### Q1.3: Thread safety?

**Answer**: **Per-call isolation**, registry reads are safe:

```python
# Registry is read-only after declaration phase
# Each call gets independent fork, no shared mutable state
# No locking needed for registry
```

### Q1.4: Registry scope?

**Answer**: **Per-evaluator**. Multiple evaluators = independent registries:

```python
# Main REPL has one evaluator
main_evaluator = Evaluator()

# Forked REPL gets its own evaluator with empty registry
forked_repl = VirtualREPL(parent, frozen_types)
# forked_repl.evaluator.synthesis_registry is separate
```

---

## 2. Tape/Fork Execution Semantics

### Q2.5: Fresh fork disposal timing?

**Answer**: **Immediately after `_execute_llm_call` returns**:

```python
def _execute_llm_call(self, context, arg):
    virtual_repl = VirtualREPL(...)  # Create
    try:
        self._llm_operate(virtual_repl, context)
        result = virtual_repl.get_it()
        return result
    finally:
        # Fork goes out of scope here, GC'd
        pass
```

### Q2.6: Fork cleanup on crash/hang?

**Answer**: **Timeout + cancellation**:

```python
class VirtualREPL:
    def __init__(self, parent, frozen_types, timeout_secs=300):
        self.timeout = timeout_secs
        self._cancelled = False
    
    def eval(self, expr):
        if self._cancelled:
            raise CancellationError("Fork cancelled")
        
        with timeout(self.timeout):
            return self._do_eval(expr)
    
    def cancel(self):
        self._cancelled = True
```

### Q2.7: Spawn vs fork distinction?

**Answer**: **Same primitive**, different usage:

```systemf
-- User explicitly calls spawn
handle = spawn (\() → someFunction arg)  -- Returns Tape a

-- Synthesized function internally creates fork
someFunction arg  -- Fresh fork created, discarded after
```

`spawn` is the primitive. Synthesized functions use it implicitly.

---

## 3. IORef Implementation

### Q3.8: Expensive/throwing initializers?

**Answer**: **Exception propagates, no rollback**:

```python
def load_module(source):
    for decl in decls:
        if is_ioref_declaration(decl):
            try:
                initial_value = evaluate(decl.initializer)
                # If this throws, module load fails
            except Exception as e:
                raise ModuleLoadError(f"IORef init failed: {e}")
```

### Q3.9: Copy vs share semantics?

**Answer**:

| Value Type | Behavior |
|-----------|----------|
| Primitives (`VInt`, `VString`) | Copied |
| `VConstructor` | Shallow copy (args shared) |
| `VClosure` | Copied (env shared) |
| `VIORef` | **Shared by reference** |
| `VTape` | Copied (but internal state shared?) |

### Q3.10: Circular IORef dependencies?

**Answer**: **Not supported** at module level:

```systemf
-- This is invalid - a and b don't exist yet
a :: IORef Int = newIORef (readIORef b)  -- ERROR: b not defined
b :: IORef Int = newIORef (readIORef a)

-- Valid: create first, then link via functions
a :: IORef Int = newIORef 0
b :: IORef Int = newIORef 0

link = \() → writeIORef b (readIORef a)  -- Runtime linking
```

---

## 4. Type System & Validation

### Q4.11: Type synonyms?

**Answer**: **Expanded before freezing**:

```python
def collect_frozen_types(ty: Type) -> set[str]:
    """Expand synonyms, collect constructors."""
    expanded = expand_synonyms(ty)
    return collect_constructors(expanded)

# type MyInt = Int
# freeze MyInt -> actually freeze Int
```

### Q4.12: Polymorphic type variables?

**Answer**: **Type variables not frozen**, their bounds are:

```systemf
-- forall a. List a → a
-- Frozen: List (the constructor)
-- Not frozen: 'a' (instantiated per call)
```

### Q4.13: Resume type validation?

**Answer**: **Runtime check**:

```python
def resume(tape: VTape) -> Value:
    """Resume and validate type matches."""
    if tape.already_resumed:
        raise RuntimeError("Tape already consumed")
    
    result = tape.execute()
    actual_type = infer_type(result)
    
    if not types_equal(actual_type, tape.return_type):
        raise TypeError(
            f"Resume type mismatch: got {actual_type}, "
            f"expected {tape.return_type}"
        )
    
    tape.already_resumed = True
    return result
```

---

## 5. LLM Tool Interface

### Q5.14: Structured data in eval?

**Answer**: **Return JSON-serializable structure**:

```python
def eval(self, expr: str) -> dict:
    value = evaluate(parse(expr))
    return {
        "value": self._serialize(value),  # JSON-compatible
        "type": str(infer_type(value)),
        "it_updated": True,
    }

def _serialize(self, value: Value):
    """Convert value to JSON-serializable format."""
    match value:
        case VPrim("Int", n): return {"_type": "Int", "value": n}
        case VPrim("String", s): return {"_type": "String", "value": s}
        case VConstructor(name, args): 
            return {"_type": name, "args": [self._serialize(a) for a in args]}
```

### Q5.15: Tool errors to LLM?

**Answer**: **Structured error object**:

```python
def eval(self, expr: str) -> dict:
    try:
        value = evaluate(parse(expr))
        return {"success": True, "value": ...}
    except Exception as e:
        return {
            "success": False,
            "error": type(e).__name__,
            "message": str(e),
        }

# LLM can check success field and handle accordingly
```

### Q5.16: Browse scope?

**Answer**: **User-defined values only**:

```python
def browse(self) -> dict:
    return {
        "values": [
            name for name in self.global_values.keys()
            if not name.startswith("_")  # No internals
            and name not in SYSTEM_NAMES  # No system primitives
        ],
        "types": [
            name for name in self.global_types.keys()
            if not name.startswith("_")
        ],
        "frozen_types": list(self.frozen_types),  # LLM should know
    }
```

---

## 6. Error Handling

### Q6.17: Timeout configuration?

**Answer**: **Configurable via pragma**:

```systemf
analyze :: Data → Result
{-# LLM model=gpt-4 timeout=600 #-}  -- 10 minutes
analyze data = ...
```

Default: 300 seconds (5 minutes)

### Q6.18: Resource limits?

**Answer**:

```python
class VirtualREPL:
    MAX_EXPR_SIZE = 10000  # characters
    MAX_RECURSION = 1000   # call stack depth
    MAX_MEMORY_MB = 100    # heap limit
    
    def eval(self, expr):
        if len(expr) > self.MAX_EXPR_SIZE:
            raise ResourceLimitError("Expression too large")
        # Apply other limits via evaluator configuration
```

### Q6.19: LLM API errors?

**Answer**: **Retry with backoff, then fail**:

```python
def _call_llm_api(self, prompt: str) -> str:
    for attempt in range(3):
        try:
            return self._do_api_call(prompt)
        except RateLimitError:
            sleep(2 ** attempt)  # Exponential backoff
        except NetworkError as e:
            if attempt == 2:
                raise LLMAPIError(f"API failed after retries: {e}")
    
    raise LLMAPIError("Max retries exceeded")
```

---

## 7. Concurrency

### Q7.20: Parallel vs cooperative?

**Answer**: **Cooperative (async) by default**, threads optional:

```python
# Default: Sequential execution
# Each fork runs to completion before returning

# Optional: True parallelism with thread pool
class ParallelEvaluator:
    def __init__(self, max_workers=4):
        self.executor = ThreadPoolExecutor(max_workers)
    
    async def execute_concurrent(self, functions: list) -> list:
        futures = [self._execute_async(f) for f in functions]
        return await asyncio.gather(*futures)
```

### Q7.21: IORef concurrent writes?

**Answer**: **Last-write-wins, no atomicity**:

```python
# No locking - simple assignment
writeIORef(ref, value):
    ref.value = value  # Race condition possible

# If deterministic behavior needed, use channels/stm (future)
```

### Q7.22: Deadlock detection?

**Answer**: **Not implemented initially**. IORefs are simple mutable cells, not locks.

---

## 8. Synthesis Implementation

### Q8.23: PrimOp generation mechanism?

**Answer**: **Hardcoded template**, not generated code:

```python
class Synthesizer:
    def synthesize(self, decl: TermDeclaration) -> SynthesisContext:
        """All synthesized LLM functions use same execution path."""
        return SynthesisContext(
            function_name=decl.name,
            frozen_types=self._collect_frozen_types(decl),
            return_type=self._extract_return_type(decl),
            llm_config=self._parse_pragma(decl.pragma),
            has_tape_param=self._has_tape_param(decl),
            # No per-function code generation!
        )

# Evaluator handles all synthesized functions uniformly
def _execute_llm_call(self, context: SynthesisContext, arg: Value):
    # Same code path for all LLM functions
    ...
```

### Q8.24: Pragma metadata extraction?

**Answer**: **Key-value pairs, minimal validation**:

```python
def parse_pragma(pragma: str) -> dict:
    """Parse 'model=gpt-4 timeout=600' -> {'model': 'gpt-4', 'timeout': '600'}."""
    result = {}
    for part in pragma.split():
        if '=' in part:
            key, value = part.split('=', 1)
            result[key] = value
        else:
            result[part] = True  # flags
    
    # Validation happens at runtime
    return result
```

### Q8.25: Caching strategy?

**Answer**: **No caching initially**. Consider memoization later:

```python
# Potential future optimization:
@lru_cache(maxsize=100)
def _execute_llm_call_cached(context_hash, arg_hash):
    ...
```

---

## 9. VirtualREPL

### Q9.26: Context inheritance details?

**Answer**:

```python
class VirtualREPL:
    def __init__(self, parent_context, frozen_types):
        # Inherited from parent:
        self.global_values = shallow_copy(parent_context.global_values)
        self.global_types = shallow_copy(parent_context.global_types)
        self.constructor_types = parent_context.constructor_types
        
        # Fresh for fork:
        self.local_bindings = {}  # 'it' and LLM-defined values
        self.frozen_types = frozen_types
```

### Q9.27: Type environment?

**Answer**: **Copy parent's type environment**:

```python
# Fork uses parent's type context as starting point
# Types defined in fork are added to local_types
# Frozen types prevent redefinition
```

### Q9.28: Module operations in fork?

**Answer**: **No :load/:import in fork** - fork is isolated:

```python
# LLM tools available: eval, typeof, browse
# No module system operations (would break isolation)
# All needed definitions must be in parent context before fork
```

---

## 10. Integration

### Q10.29: Module loading order?

**Answer**: **Sequential, dependencies first**:

```python
def load_modules(modules: list[str]):
    for module_path in modules:
        source = read_file(module_path)
        module = compile_module(source)
        
        # Synthesis happens during compilation
        for decl in module.declarations:
            if has_llm_pragma(decl):
                synthesizer.synthesize(decl)  # Registers in evaluator
```

### Q10.30: Namespace pollution?

**Answer**: **Synthesized functions are normal functions**:

```python
# After synthesis:
# - Function appears in global_values
# - Can be called normally: analyze myData
# - Appears in browse results
# - Can be passed as argument: map analyze datasets
```

### Q10.31: REPL interaction?

**Answer**: **Direct REPL usage supported**:

```systemf
> analyze "hello"
"bonjour"  -- Result

> :t analyze
Data → Result  -- Type shown

> :browse
analyze :: Data → Result  -- Listed among values
```

---

## Summary of Additional Decisions

| Topic | Decision |
|-------|----------|
| Registry cleanup | Session end |
| Fork disposal | After function returns |
| Timeout | Configurable, default 5min |
| IORef circular deps | Not supported at module level |
| Type synonyms | Expanded before freezing |
| Concurrent IORef | Last-write-wins, no atomicity |
| Error format | Structured JSON |
| Browse scope | User values only |
| Synthesis | Hardcoded template, no per-function code |
| Fork isolation | No :load/:import |
| REPL usage | Fully supported |
