# System F LLM Synthesizer Design - Q&A

**Status**: Draft - Answers to Review Questions

---

## 1. PrimOp Body / Core AST Structure

### Q1.1: What is the actual Core AST structure?

**Answer**: The synthesized PrimOp is **opaque** - it does NOT contain a Core AST expression tree. The PrimOp acts as a foreign function interface (FFI) marker:

```python
@dataclass(frozen=True)
class PrimOp(Term):
    """Primitive operation - opaque implementation in evaluator."""
    name: str  # e.g., "llm.analyze"
    # No body, no implementation - evaluator handles it via name lookup
```

The actual implementation lives in the evaluator's `_make_primop_closure` method, which looks up the synthesis context from a registry.

### Q1.2: How does the PrimOp capture synthesis context?

**Answer**: The context is stored in a **global registry keyed by function name**:

```python
# In evaluator
self.synthesis_registry: dict[str, SynthesisContext] = {}

# At declaration time
synthesizer.synthesize(decl)  # Creates and registers context
# Returns: PrimOp(name="llm.analyze")  # No context embedded

# At runtime
evaluator.evaluate(PrimOp(name="llm.analyze"))  # Looks up in registry
```

This keeps the Core AST minimal and allows redefinition (new synthesis context overwrites old).

### Q1.3: Relationship between SynthesisContext and LLMMetadata?

**Answer**: `SynthesisContext` is the **compile-time** artifact, `LLMMetadata` is the **runtime** artifact:

```python
@dataclass
class SynthesisContext:
    """Created at declaration time by synthesizer."""
    function_name: str
    frozen_types: set[str]
    return_type: Type
    llm_config: dict  # model, temperature, etc.
    has_tape_param: bool
    
    def to_metadata(self) -> LLMMetadata:
        """Convert to runtime metadata for evaluator."""
        return LLMMetadata(
            function_name=self.function_name,
            frozen_types=self.frozen_types,
            return_type=self.return_type,
            ...
        )
```

---

## 2. Tape and Forked REPL Relationship

### Q2.1: When is Tape passed vs fresh fork?

**Answer**: **Explicit parameter**. The synthesizer checks if the function signature includes a Tape parameter:

```systemf
-- Fresh fork created automatically
analyze :: Data → Result
{-# LLM model=gpt-4 #-}
analyze data = ...

-- Uses provided Tape (resume from previous session)
analyzeWithContext :: Tape Result → Data → Result
{-# LLM model=gpt-4 #-}
analyzeWithContext tape data = ...
```

The synthesizer generates different PrimOp behavior based on `has_tape_param`.

### Q2.2: What happens to the fork after LLM operation?

**Answer**: 
- **Fresh fork**: Discarded after retrieving `it`. No Tape is created.
- **Tape parameter**: The Tape's internal REPL state is updated (the LLM's operations mutate it).

If you want to capture the fork as a Tape for later use, use the `fork` primitive explicitly:

```systemf
task = spawn (\() → analyze data)  -- Returns Tape Result
result = resume task              -- Blocks, returns Result
```

### Q2.3: Who calls `to_tape()`?

**Answer**: The **user** calls it via the `spawn` primitive:

```python
# spawn primitive implementation
def spawn(thunk: Callable[[], Value], return_type: Type) -> VTape:
    frozen_types = collect_type_dependencies(return_type)
    repl = VirtualREPL(parent_context, frozen_types)
    # Don't execute yet - just create tape
    return VTape(
        session_id=generate_id(),
        return_type=return_type,
        frozen_types=frozen_types,
        repl_state=repl,
        thunk=thunk,  # Store for later execution
    )
```

### Q2.4: How does `fork` primitive relate to synthesis?

**Answer**: `fork` is a **separate primitive** from synthesized LLM functions. Synthesis creates opaque PrimOps. `fork` is a regular primitive that users call explicitly:

```systemf
-- User code
handle = fork (\() → analyze data)  -- Creates Tape
result = resume handle             -- Executes in fork
```

---

## 3. IORef Across Module Boundaries

### Q3.1: What is IORef scope?

**Answer**: **Session-scoped**. IORefs are tied to the REPL session:

```
Module A: counter = newIORef 0
Module B: increment = \n → writeIORef counter (readIORef counter + n)

-- Same session: Both see same counter
-- Different sessions: Each has its own counter
```

This provides isolation between concurrent LLM calls while allowing state sharing within a session.

### Q3.2: How to handle name collisions?

**Answer**: IORefs are **values**, not global variables. They follow normal lexical scope:

```systemf
-- Module A
counterA :: IORef Int = newIORef 0

-- Module B
counterB :: IORef Int = newIORef 0  -- Different IORef!

-- To share, explicitly pass or import the binding
import A (counterA)
```

### Q3.3: When is newIORef executed?

**Answer**: **At module load time** (eager):

```python
# When :load module.sf executes
def load_module(source):
    decls = parse(source)
    for decl in decls:
        if is_ioref_declaration(decl):
            # Execute immediately
            initial_value = evaluate(decl.initializer)
            ioref = VIORef(initial_value)
            global_env[decl.name] = ioref
```

### Q3.4: How does VirtualREPL access IORefs?

**Answer**: IORefs are **copied by reference** (shallow copy):

```python
class VirtualREPL:
    def __init__(self, parent_context, frozen_types):
        # Shallow copy - IORef objects shared
        self.global_values = {
            name: value for name, value in parent_context.global_values.items()
        }
        # VIORef objects are shared, primitives are copied
```

---

## 4. IORef State in Forked Context

### Q4.1-Q4.4: IORef mutation semantics?

**Answer**: **Affects only the fork** (snapshot semantics with shared references):

```python
# Parent session
counter = VIORef(0)  # value = 0

# Fork
child_repl = VirtualREPL(parent, frozen_types={})
# child_repl.global_values["counter"] is SAME VIORef object

# LLM writes in fork
writeIORef(counter, 42)  # counter.value = 42

# Parent sees the change!
readIORef(counter)  # Returns 42
```

**This is intentional**: IORefs provide **cross-fork shared mutable state**.

**For isolation**: Don't use IORefs, use regular immutable values.

---

## 5. Synthesis Context Resolution

### Q5.1-Q5.4: How does evaluator find synthesis context?

**Answer**: **Registry lookup by function name**:

```python
class Evaluator:
    def __init__(self):
        self.synthesis_registry: dict[str, SynthesisContext] = {}
    
    def register_llm_function(self, name: str, context: SynthesisContext):
        """Called by synthesizer at declaration time."""
        self.synthesis_registry[name] = context
    
    def _make_primop_closure(self, name: str) -> Value:
        """Called when evaluating PrimOp."""
        if name.startswith("llm."):
            func_name = name[4:]  # Strip "llm." prefix
            context = self.synthesis_registry[func_name]
            return self._make_llm_wrapper(context)
```

**Redefinition**: New declaration overwrites registry entry.

**Shadowing**: Not supported - function names must be unique per session.

---

## 6. LLM Tool Interface

### Q6.1-Q6.4: What tools does LLM have access to?

**Answer**: Minimal interface (3 tools):

```python
class VirtualREPLTools:
    """Tools available to LLM operating on virtual REPL."""
    
    def eval(self, expr: str) -> dict:
        """Evaluate expression, return {value: ..., type: ..., it_updated: bool}."""
        term = parse(expr)
        core_term = elaborate(term, self.repl_context)
        value = evaluate(core_term)
        type = typeof(value)
        
        # Update 'it' binding
        self.repl_context.global_values["it"] = value
        self.repl_context.global_types["it"] = type
        
        return {
            "value": str(value),
            "type": str(type),
            "it_updated": True
        }
    
    def typeof(self, expr: str) -> str:
        """Get type of expression without evaluating."""
        term = parse(expr)
        _, type = infer_type(term, self.repl_context)
        return str(type)
    
    def browse(self) -> dict:
        """List available values and types in context."""
        return {
            "values": list(self.repl_context.global_values.keys()),
            "types": list(self.repl_context.global_types.keys()),
        }
```

**Tool calling**: JSON-RPC style (OpenAI function calling compatible):

```json
{
  "tool_calls": [{
    "id": "call_1",
    "type": "function",
    "function": {
      "name": "eval",
      "arguments": "{\"expr\": \"1 + 1\"}"
    }
  }]
}
```

---

## 7. Type System and Validation

### Q7.1-Q7.3: Type validation details?

**Answer**:

**Q7.1 Type mismatch**: Raise `TypeError` (exception):

```python
def _execute_llm_call(self, context: SynthesisContext, arg: Value) -> Value:
    ...
    result = virtual_repl.get_it()
    actual_type = infer_type(result)
    
    if not types_equal(actual_type, context.return_type):
        raise TypeError(
            f"LLM function {context.function_name} returned {actual_type}, "
            f"expected {context.return_type}"
        )
    
    return result
```

**Q7.2 Tape type**: `Tape a` is **phantom type** at runtime:

```python
@dataclass
class VTape(Value):
    return_type: Type  # Runtime type for validation
    ...

# Type parameter 'a' is erased at runtime like all types
# But we store it for validation when resuming
```

**Q7.3 Frozen types**: Only return type and its dependencies are frozen:

```python
def collect_frozen_types(return_type: Type) -> set[str]:
    """Types that cannot be redefined in fork."""
    return collect_type_dependencies(return_type)
    # Argument types are NOT frozen - they just need to exist
```

---

## 8. Error Handling and Edge Cases

### Q8.1-Q8.3: Edge cases?

**Answer**:

**Never sets `it`**: Timeout after N turns, return `VError "No result produced"`.

**Wrong type**: `TypeError` exception (see Q7.1).

**Infinite loop**: Timeout mechanism in VirtualREPL.

**Invalid tool call**: Return error to LLM, let it retry.

**Synthesis failure**: Declaration-time error (parse/type error in metadata).

**Recursive calls**: Each call creates nested fork (standard behavior).

---

## 9. Concurrency and Performance

### Q9.1-Q9.2: Concurrency?

**Answer**: 

**Multiple concurrent calls**: Each gets **own fork**:

```python
# Call 1
fork1 = VirtualREPL(parent, frozen_types)

# Call 2 (concurrent)  
fork2 = VirtualREPL(parent, frozen_types)
# fork1 and fork2 are independent
```

**Shared state**: Only IORefs are shared (by reference).

**Type definitions**: Shared (immutable), but frozen types prevent redefinition.

---

## 10. Documentation Contradictions

### D10.1-D10.3: Clarifications?

**D10.1 Error handling**: Use **exceptions** for type mismatch (not Result type). Synthesis failures use Result type at declaration time.

**D10.2 fork primitive**: `fork` is **both** user-callable primitive AND used internally. User can call it explicitly or let synthesized function handle it.

**D10.3 Tape parameter**: LLM functions can **optionally** take Tape. The synthesizer detects this from the signature:

```python
def has_tape_parameter(decl: TermDeclaration) -> bool:
    """Check if first parameter is Tape type."""
    arg_types = extract_arg_types(decl.type_annotation)
    return arg_types and is_tape_type(arg_types[0])
```

---

## Summary

| Question Category | Key Decision |
|------------------|--------------|
| Core AST | Opaque PrimOp with registry lookup |
| Tape lifecycle | Fresh fork (discarded) or explicit Tape param |
| IORef | Session-scoped, shared across forks |
| Tool interface | 3 tools (eval, typeof, browse), JSON-RPC |
| Context lookup | Registry by function name |
| Type validation | Exception on mismatch |
| Concurrency | Independent forks, shared IORefs |
