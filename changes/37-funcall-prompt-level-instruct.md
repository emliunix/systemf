# 37: Funcall Prompt-Level Instruct

**Date:** 2026-05-06
**Status:** Done
**Area:** `bub_sf/src/bub_sf/bub_ext.py`

## Problem

The `{-# LLM #-}` pragma generates function calling prompts, but the model often fails to follow the expected funcall format. We need to inject a prominent instruction that tells the model to strictly follow the funcall documentation.

## Design

Inject a hardcoded `<rules>` tag at the top of every funcall prompt. The existing `<doc>` tags (from the function's docstring) serve as the actual instructions — the `<rules>` tag simply frames them as mandatory requirements.

### Implementation

In `_build_func_prompt()` (line 211):

```python
def _lines() -> Generator[str, None, None]:
    yield "<rules>Strictly follow the instructions funcall doc to complete the funcall</rules>"
    yield f"""<funcall mod="{name.mod}" source="{name.loc}" name="{name.surface}">"""
    if doc:
        yield f"<doc>{doc}</doc>"
    ...
```

The prompt structure becomes:
```xml
<rules>Strictly follow the instructions funcall doc to complete the funcall</rules>
<funcall mod="..." name="...">
  <doc>Given the user input, guess and return ONLY the user's intent...</doc>
  <args>...</args>
  <return type="..." />
</funcall>
```

### Why This Works

- The `<rules>` tag is placed **before** the `<funcall>` tag, giving it maximum prominence
- The actual instruction content lives in the docstring (SystemF `doc` field), which is already visible to the programmer
- No new pragma syntax needed — docstrings are the natural place for instructions
- The hardcoded rule is simple and unambiguous: "follow the doc"

## Files

- `bub_sf/src/bub_sf/bub_ext.py` — add `<rules>` tag to `_build_func_prompt()`

## Related

- `status.md` item 19
- `changes/38-notools-llm-pragma.md` — sibling pragma feature
