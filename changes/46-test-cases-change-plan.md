# Test Cases Change Plan for CP44 (ChatClient Architectural Refactor)

## Overview

This document maps every test case in the `republic/tests/` directory to the new architecture defined in `changes/44-chatclient-architectural-refactor.md`. For each test, we specify:
- **Status**: VALID (still relevant), REWRITE (needs modification), or DELETE (no longer applicable)
- **New Component**: Which layer the test should target under the new architecture
- **New File**: Where the test should live after migration

---

## Architecture Layers

| Layer | Responsibility | Test File |
|-------|---------------|-----------|
| `ChatClient` | Transport parsing, request building, stream event emission | `test_chat_client_v2.py` |
| `TapeSession` | Read/write tape entries, message reconstruction, turn lifecycle | `test_tape_session.py` |
| `ToolExecutor` | Tool execution (sync + async) | `test_tools_contract.py` |
| `AsyncTapeManager` | Tape storage/query operations | `test_tape_contract.py` |
| `Auth/OAuth` | Authentication resolvers and login flows | `test_auth_resolver.py` |
| `ProviderPolicies` | Provider-specific behavior rules | `test_provider_policies.py` |
| `ParsingRegistry` | Transport parser selection and capabilities | `test_parsing_registry.py` |

> **Note**: The `AgentRunner` layer was removed from the architecture (see `changes/47-remove-agentrunner-from-plan.md`). The orchestration loop is written directly by callers using TapeSession + ToolExecutor primitives.

---

## Full Test Case Mapping Table

### `test_chat_client_v2.py` (NEW - CP44)

| # | Test Case | Status | New Component | New File | Notes |
|---|-----------|--------|--------------|----------|-------|
| 1 | `test_chat_returns_text_result` | VALID | ChatClient.chat() | `test_chat_client_v2.py` | Tests non-streaming text response |
| 2 | `test_chat_returns_tool_calls` | VALID | ChatClient.chat() | `test_chat_client_v2.py` | Tests non-streaming tool call parsing |
| 3 | `test_chat_returns_error_on_exception` | VALID | ChatClient.chat() | `test_chat_client_v2.py` | Tests error wrapping in LLMResult |
| 4 | `test_stream_yields_text_events_and_final` | VALID | ChatClient.stream() | `test_chat_client_v2.py` | Tests streaming text + final event |
| 5 | `test_stream_returns_error_event_on_failure` | VALID | ChatClient.stream() | `test_chat_client_v2.py` | Tests ErrorEvent on stream failure |
| 6 | `test_chat_passes_tools_to_core` | VALID | ChatClient.chat() | `test_chat_client_v2.py` | Tests tools forwarded to LLM core |

**Gap**: No test for streaming with tool calls (tool call deltas → FinalEvent with tool_calls). Should add.

---

### `test_tape_session.py` (NEW - CP44)

| # | Test Case | Status | New Component | New File | Notes |
|---|-----------|--------|--------------|----------|-------|
| 1 | `test_prepare_records_user_message` | VALID | TapeSession.prepare() | `test_tape_session.py` | Tests system + user entry creation |
| 2 | `test_run_records_assistant_message` | VALID | TapeSession.run() | `test_tape_session.py` | Tests assistant entry + run event |
| 3 | `test_run_returns_tool_call_needed` | VALID | TapeSession.run() | `test_tape_session.py` | Tests ToolCallNeeded return |
| 4 | `test_add_tool_results_records_tool_result` | VALID | TapeSession.add_tool_results() | `test_tape_session.py` | Tests tool_result entry + continuation |
| 5 | `test_complete_adds_extra_entries` | VALID | TapeSession.complete() | `test_tape_session.py` | Tests completion event |
| 6 | `test_handoff_appends_anchor` | VALID | TapeSession.handoff() | `test_tape_session.py` | Tests anchor + handoff entries |
| 7 | `test_append_event_records_framework_event` | VALID | TapeSession.append_event() | `test_tape_session.py` | Tests framework event entry |

**Gap**: No test for streaming (TapeSession.stream()). Should add.

---

### `test_tape_contract.py` (REWRITTEN - needs fixes)

| # | Test Case | Status | New Component | New File | Notes |
|---|-----------|--------|--------------|----------|-------|
| 1 | `test_build_messages_uses_last_anchor_slice` | REWRITE | AsyncTapeManager.read_messages() | `test_tape_contract.py` | Async fixture error. Uses `@pytest.fixture` + `@pytest.mark.asyncio` incorrectly. Fix: use `@pytest_asyncio.fixture` |
| 2 | `test_build_messages_reports_missing_anchor` | REWRITE | AsyncTapeManager.read_messages() | `test_tape_contract.py` | Same async fixture issue as #1 |
| 3 | `test_async_manager_awaits_context_selector_after_anchor_slice` | REWRITE | AsyncTapeManager.read_messages() | `test_tape_contract.py` | FAILS: `select` callback receives coroutine from `fetch_all` but test does `list(entries)` synchronously. Must await or use `async for`. |
| 4 | `test_query_between_anchors_and_limit` | REWRITE | TapeQuery | `test_tape_contract.py` | **Two issues**: (1) sync `store.append()` now async, (2) TapeQuery API changed: no longer accepts `store` param, `.all()` removed. Use `await store.fetch_all(query)`. |
| 5 | `test_query_text_matches_payload_and_meta` | REWRITE | TapeQuery | `test_tape_contract.py` | Same two issues as #4 |
| 6 | `test_query_between_dates_filters_inclusive_range` | REWRITE | TapeQuery | `test_tape_contract.py` | Same two issues as #4 |
| 7 | `test_query_combines_anchor_date_and_text_filters` | REWRITE | TapeQuery | `test_tape_contract.py` | Same two issues as #4 |

---

### `test_auth_resolver.py` (UNCHANGED)

| # | Test Case | Status | New Component | New File | Notes |
|---|-----------|--------|--------------|----------|-------|
| 1 | `test_codex_cli_api_key_resolver_reads_access_token` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 2 | `test_openai_codex_oauth_resolver_refreshes_expiring_token` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 3 | `test_openai_codex_oauth_resolver_returns_none_when_expired_and_refresh_fails` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 4 | `test_openai_codex_oauth_resolver_uses_current_token_if_refresh_fails_but_not_expired` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 5 | `test_github_copilot_oauth_resolver_prefers_persisted_token` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 6 | `test_github_copilot_oauth_resolver_uses_github_cli_token_when_local_file_missing` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 7 | `test_github_copilot_oauth_resolver_returns_none_for_other_provider` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 8 | `test_load_github_cli_oauth_token_reads_hosts_yaml` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 9 | `test_load_github_cli_oauth_token_via_command` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 10 | `test_login_github_copilot_oauth_success_persists_tokens` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 11 | `test_login_github_copilot_oauth_raises_when_user_denies` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 12 | `test_login_openai_codex_oauth_success_persists_tokens` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 13 | `test_login_openai_codex_oauth_raises_on_state_mismatch` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 14 | `test_login_openai_codex_oauth_raises_on_missing_code` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 15 | `test_login_openai_codex_oauth_uses_local_callback_without_prompt` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |
| 16 | `test_login_openai_codex_oauth_raises_without_prompt_and_without_callback` | VALID | Auth resolver | `test_auth_resolver.py` | No CP44 impact |

**Note**: `test_auth_resolver.py` imports deprecated `LLM` class from `republic` (line 7). While unused in tests, the import will break if `LLM` shim is removed.

---

### `test_tools_contract.py` (UNCHANGED)

| # | Test Case | Status | New Component | New File | Notes |
|---|-----------|--------|--------------|----------|-------|
| 1 | `test_tool_from_model_validates_payload` | VALID | ToolExecutor.execute() | `test_tools_contract.py` | No CP44 impact |
| 2 | `test_context_tool_requires_context` | VALID | ToolExecutor.execute() | `test_tools_contract.py` | No CP44 impact |
| 3 | `test_normalize_tools_rejects_duplicate_names` | VALID | normalize_tools() | `test_tools_contract.py` | No CP44 impact |
| 4 | `test_convert_tools_rejects_schema_only_tools` | VALID | Tool.convert_tools() | `test_tools_contract.py` | No CP44 impact |
| 5 | `test_sync_execute_rejects_async_handler` | VALID | ToolExecutor.execute() | `test_tools_contract.py` | No CP44 impact |
| 6 | `test_execute_async_supports_async_handler` | VALID | ToolExecutor.execute_async() | `test_tools_contract.py` | No CP44 impact |

---

### `test_provider_policies.py` (UNCHANGED)

| # | Test Case | Status | New Component | New File | Notes |
|---|-----------|--------|--------------|----------|-------|
| 1 | `test_responses_rejection_reason_none_when_openrouter_responses_available` | VALID | provider_policies | `test_provider_policies.py` | No CP44 impact |
| 2 | `test_responses_rejection_reason_for_provider_without_responses` | VALID | provider_policies | `test_provider_policies.py` | No CP44 impact |
| 3 | `test_responses_rejection_reason_for_openrouter_anthropic_tools` | VALID | provider_policies | `test_provider_policies.py` | No CP44 impact |
| 4 | `test_supports_messages_format` | VALID | provider_policies | `test_provider_policies.py` | No CP44 impact |
| 5 | `test_completion_stream_usage_policy` | VALID | provider_policies | `test_provider_policies.py` | No CP44 impact |
| 6 | `test_completion_max_tokens_arg_policy` | VALID | provider_policies | `test_provider_policies.py` | No CP44 impact |
| 7 | `test_provider_policy_uses_exact_match_not_substring` | VALID | provider_policies | `test_provider_policies.py` | No CP44 impact |

---

### `test_parsing_registry.py` (1 FAILURE)

| # | Test Case | Status | New Component | New File | Notes |
|---|-----------|--------|--------------|----------|-------|
| 1 | `test_parser_for_transport_returns_parser_objects` | VALID | parser_for_transport() | `test_parsing_registry.py` | Tests parser selection. No CP44 impact. |
| 2 | `test_responses_extract_tool_calls_accepts_full_response` | VALID | BaseTransportParser | `test_parsing_registry.py` | Tests responses parser. No CP44 impact. |
| 3 | `test_chat_client_resolve_transport_treats_output_text_as_responses` | **DELETE** | N/A | N/A | References removed `ChatClient._is_non_stream_response` and `ChatClient._extract_text`. These were static method shims removed in CP44 Phase 2. The transport detection logic is now internal to ChatClient.chat()/stream(). |

**Recommendation**: Delete test #3. Transport detection is tested implicitly by `test_chat_client_v2.py` via the `FakeLLMCore` integration.

---

### `test_docs_and_examples.py` (UNCHANGED)

| # | Test Case | Status | New Component | New File | Notes |
|---|-----------|--------|--------------|----------|-------|
| 1 | `test_markdown_python_blocks_are_valid_python` | VALID | Documentation | `test_docs_and_examples.py` | No CP44 impact |
| 2 | `test_examples_are_valid_python` | VALID | Examples | `test_docs_and_examples.py` | No CP44 impact |

---

## Deleted Test Files (Pre-CP44 Cleanup)

The following test files were deleted during CP44 implementation because they tested APIs that no longer exist:

| File | Rationale | Replacement |
|------|-----------|-------------|
| `test_github_copilot_transport.py` | Tested old `ChatClient` transport-specific behavior (GitHub Copilot headers, API base normalization). These are now internal to `ChatClient.chat()`/`stream()` and tested via `test_chat_client_v2.py` + fakes. | `test_chat_client_v2.py` |
| `test_openai_codex_transport.py` | Tested old `ChatClient` OpenAI Codex transport. Same rationale as above. | `test_chat_client_v2.py` |
| `test_responses_handling.py` | Tested old `ChatClient` Responses API handling (output_text, reasoning, compaction). Now handled by `_ParseAccumulator` inside `ChatClient`. | `test_chat_client_v2.py` (gaps noted) |
| `test_user_experience.py` | Tested old `LLM` facade methods (`stream_events_async`, `run_tools_async`, `chat_async`). These methods are removed from `LLM` facade. User-facing orchestration is now the caller's loop via `TapeSession` + `ToolExecutor`. | `test_tape_session.py` |

---

## Test Gaps (Missing Coverage)

| Gap | Priority | Component | Suggested Test |
|-----|----------|-----------|----------------|
| Streaming with tool calls | HIGH | ChatClient.stream() | `test_stream_yields_tool_call_events` - verify tool call deltas accumulate into FinalEvent.result.tool_calls |
| TapeSession.stream() | HIGH | TapeSession | `test_stream_records_entries_and_yields_turn_result` - verify streaming turns append entries |
| Full tool execution loop | MEDIUM | TapeSession (integration) | `test_full_tool_loop_executes_and_returns_final` - verify prepare → run → add_tool_results → run → complete |
| ErrorEvent handling in TapeSession | MEDIUM | TapeSession | `test_run_records_error_entry` - verify error responses create error entries |
| Dual-save format verification | MEDIUM | TapeSession | `test_run_creates_dual_tool_call_entries` - verify both message.tool_calls + separate tool_call entry |
| build_messages with tool results | MEDIUM | AsyncTapeManager | `test_build_messages_includes_tool_results` - verify tool_result entries become role:tool messages |
| Tool execution failure in loop | MEDIUM | TapeSession (integration) | `test_tool_loop_handles_execution_errors` - verify error propagation when ToolExecutor returns errors |
| TapeSession.stream() error handling | MEDIUM | TapeSession | `test_stream_propagates_errors` - verify ErrorEvent propagation through TapeSession.stream() |
| max_iterations enforcement | LOW | Caller's loop | `test_loop_respects_max_iterations` - verify tool call loop terminates at limit |

---

## Summary Statistics

| Category | Count |
|----------|-------|
| **VALID (no changes)** | 33 |
| **REWRITE (needs fixes)** | 8 |
| **DELETE** | 1 |
| **NEW (already written)** | 13 |
| **Gaps to fill** | 9 |
| **Total current test cases** | 54 |

---

## Action Items

1. **Fix async fixtures** in `test_tape_contract.py` (tests 1-2): Use `@pytest_asyncio.fixture` instead of `@pytest.fixture` for async fixtures
2. **Fix sync append calls** in `test_tape_contract.py` (tests 4-7): Convert `store.append()` calls to `await store.append()` and update TapeQuery API usage (remove `store` param, use `await store.fetch_all(query)`)
3. **Fix async iteration** in `test_tape_contract.py` (test 3): `select` callback must await coroutine or use `async for`
4. **Delete** `test_chat_client_resolve_transport_treats_output_text_as_responses` from `test_parsing_registry.py`
5. **Add missing tests** for streaming tool calls, TapeSession.stream(), full tool execution loop
6. **Verify** `test_docs_and_examples.py` still passes (examples may reference deleted APIs)
