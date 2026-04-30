so record some of the patterns I came up:

- traces: a separate topics tracking tape (context) lives alongside the main tape, after each turn it summarizes the topic and development, and keep in it's own context.
- recall: analyze user intention, and topics from history and tracked topics. detect topic switch, and pull enough information to inject into the prompt
- ask_parent: on fork, the parent tape is passed down to subagent, and when the subagent needs more information, it can spawn a special ask tool (which is a nested subagent with parent's tape snapshot), so it should be restricted to chat only, no tool calls. And those asks will be passed back to parent on finish.
- ask_child: the same, but in the other direction. the subagent may return not only the result, but also it's tape (not the merge back behavior, but just a pointer to it's finalized state). so the parent can push to ask more information or resume with another task.
- saved_child: continue of ask_child, so we can make the child explore first and return when it has enough context. and the parent decides to keep a snapshot of it. and resume it later maybe in parallel for different kinds of tasks.
- supervised: an accompany agent can not only summarize and inject context, but also supervise with more topic focused mind. so when it's detected it gets distracted or fall into a repeated error hell, we can inject a forced phase change to rethink/reorganize the work
- setup_constriants: to not be distracted, we can set say folder list r/w permissions, tool call allow list, with the reasons explained to start real tool calls.

## ACL Unlock Pattern

A pattern of agentic tool usage that forces deliberation before action while minimizing human burden:

- **Locked-by-default**: All tools are visible but locked. A maximum ACL scope is defined upfront, but the agent starts with no permissions.
- **Unlock protocol**: The first call to a locked tool errors, requiring the agent to invoke a special `unlock` tool. This tool accepts an ACL list plus reasoning for why each tool is needed.
- **Lightweight review**: A separate reviewer agent evaluates the request. Most reasonable requests are approved automatically, so human interaction burden stays low.
- **Friction by design**: The extra step forces the agent to think through its actions before executing, reducing unnecessary or incorrect tool calls.

**Extension — Auto Revoke:**

An accompany agent (running with separate context) tracks the main agent's intentions and flow. When it observes that an approved ACL reason no longer applies, it injects a `revoke` to remove the permission. This shrinks the attack surface over time without manual cleanup.

