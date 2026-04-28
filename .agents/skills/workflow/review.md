# Review Process

This document defines the review process for the Architect role.

## Overview

The review process validates implementation quality and correctness against design specifications. Reviews are triggered when a task with `type: review` is assigned to an Architect.

## Review Workflow

```
review_mode(task_file)
│
├─ Step 1: Load Context
│  ├─ Read task metadata and work log
│  ├─ Identify files modified in implementation
│  └─ Load original specification from refers field
│
├─ Step 2: Analyze Changes
│  ├─ Review code changes in modified files
│  ├─ Identify potential issues (bugs, anti-patterns, inconsistencies)
│  ├─ Check if changes modify core types / protocols / test definitions
│  └─ Assess impact on system assumptions
│
├─ Step 3: Evaluate Compliance
│  ├─ Compare implementation against specification
│  ├─ Check if behavior matches expected contracts
│  ├─ Verify architecture principles are followed
│  └─ Identify deviations and their severity
│
├─ Step 4: Make Decision
│  ├─ IF critical issues found:
│  │   ├─ Generate work items for fixes
│  │   ├─ Log escalation with work items
│  │   └─ Return "escalate"
│  │
│  └─ IF acceptable or minor issues:
│      ├─ Document findings
│      ├─ Log pass
│      └─ Return "pass"
```

## Step-by-Step Review

### Step 1: Load Context

```python
def load_review_context(task_file):
    """
    Load all necessary context for the review.
    
    Returns context containing:
    - task_meta: Task metadata (role, type, skills, etc.)
    - work_log: Previous work log entries
    - modified_files: List of files modified in implementation
    - original_spec: Design specification from refers field
    - implementation: Content of modified files
    """
    pass
```

### Step 2: Analyze Changes

```python
def analyze_code_changes(modified_files, original_spec):
    """
    Analyze implementation changes for issues.
    
    Review checklist:
    - [ ] Code follows style guidelines
    - [ ] No obvious bugs or logic errors
    - [ ] Error handling is appropriate
    - [ ] No security vulnerabilities introduced
    - [ ] Performance implications considered
    
    Anti-patterns to flag:
    - Workarounds or temporary solutions
    - TODO/FIXME markers in code
    - Copy-pasted code without adaptation
    - Overly complex or convoluted logic
    - Missing error handling
    
    Returns:
        List of issues found with severity and description
    """
    pass


def check_core_modifications(modified_files, original_spec):
    """
    Check if implementation modifies core system components.
    
    Core components to monitor:
    - types.py or type definitions
    - Protocol interfaces
    - Public API contracts
    - Test definitions and contracts
    - Configuration schemas
    
    For each modification:
    - Does it break backward compatibility?
    - Does it violate system assumptions?
    - Are dependent components affected?
    - Is the change intentional and documented?
    
    Returns:
        List of core modifications with impact assessment
    """
    pass
```

### Step 3: Evaluate Compliance

```python
def evaluate_spec_compliance(implementation, original_spec, core_mods):
    """
    Evaluate if implementation meets specification.
    
    Compliance checks:
    - Types match specification (unless intentionally modified)
    - Interfaces match specification
    - Behavior matches expected contracts
    - Architecture principles followed
    
    Deviation handling:
    - Intentional deviations: Must be documented with rationale
    - Unintentional deviations: Issues to fix
    - Core type changes: Must not break system assumptions
    
    Args:
        implementation: Implementation content
        original_spec: Original design specification
        core_mods: Core modifications from check_core_modifications()
        
    Returns:
        (compliance_status, deviations, assessment)
        compliance_status: "full", "partial", "none"
        deviations: List of deviations with rationale
        assessment: "acceptable", "needs_fix", "critical"
    """
    pass
```

### Step 4: Decision and Logging

```python
def make_review_decision(issues, core_mods, compliance):
    """
    Make pass/escalate decision based on review findings.
    
    Decision criteria:
    
    PASS if:
    - No critical issues
    - Compliance is "full" or "partial" with documented rationale
    - Core modifications don't break system assumptions
    - Minor issues can be addressed in follow-up
    
    ESCALATE if:
    - Critical bugs or security issues found
    - Core modifications break system assumptions
    - Compliance is "none" or "partial" without acceptable rationale
    - Implementation fundamentally doesn't meet specification
    
    Returns:
        (decision, work_items, reasoning)
        decision: "pass" or "escalate"
        work_items: List of work items if escalating
        reasoning: Explanation of decision
    """
    pass


def log_review_result(task_file, decision, findings, work_items=None):
    """
    Log review result using log-task.py script.
    
    For PASS:
    - Facts: What was reviewed
    - Analysis: Why implementation meets spec
    - Conclusion: PASS
    
    For ESCALATE:
    - Facts: What was reviewed, issues found
    - Analysis: Root causes, impact assessment
    - Conclusion: ESCALATE with required fixes
    - Additional Work Items: Prerequisite tasks to create
    
    Args:
        task_file: Path to task file
        decision: "pass" or "escalate"
        findings: Review findings and issues
        work_items: Work items to create if escalating
    """
    # Use log-task.py to write work log
    # execute_script(f"{skill_path}/scripts/log-task.py", ...)
    pass
```

## Review Output Format

### Pass Output

```markdown
## Work Log

### [timestamp] Implementation Review | ok

**Facts:**
- Reviewed implementation in files: [list]
- Checked against specification from [design task]
- No critical issues found

**Analysis:**
- Implementation follows design specification
- Code quality: [assessment]
- Architecture compliance: [assessment]
- [Any minor issues or notes]

**Conclusion:**
- **PASS** - Implementation approved
- Ready for integration
```

### Escalate Output

```markdown
## Work Log

### [timestamp] Implementation Review | escalate

**Facts:**
- Reviewed implementation in files: [list]
- Found [N] critical issues
- Core modifications detected: [list]
- Specification deviations: [list]

**Analysis:**
- [Issue 1]: [description and root cause]
- [Issue 2]: [description and root cause]
- Impact: [assessment of impact on system]
- Required fixes identified below

**Conclusion:**
- **ESCALATE** - Implementation requires fixes before approval
- Same task file continues; prerequisite tasks needed

## Additional Work Items

```yaml
additional_work_items:
  - description: Fix [specific issue]
    files: [affected files]
    expertise_required: [skills]
    priority: [critical/high/medium]
    notes: [root cause and fix approach]
```

**Manager Note:** Create tasks from work items above and add as dependencies to this task.
```

## Integration with role-architect.md

The review process is called from `review_mode()` in role-architect.md:

```python
def review_mode(task_file):
    """
    Review implementation against design specification.
    
    See review.md for detailed review process.
    """
    # Step 1: Load context
    context = load_review_context(task_file)
    
    # Step 2: Analyze changes
    issues = analyze_code_changes(context.modified_files, context.original_spec)
    core_mods = check_core_modifications(context.modified_files, context.original_spec)
    
    # Step 3: Evaluate compliance
    compliance, deviations, assessment = evaluate_spec_compliance(
        context.implementation, 
        context.original_spec,
        core_mods
    )
    
    # Step 4: Make decision and log
    decision, work_items, reasoning = make_review_decision(issues, core_mods, compliance)
    log_review_result(task_file, decision, {
        "issues": issues,
        "core_modifications": core_mods,
        "compliance": compliance,
        "deviations": deviations,
        "reasoning": reasoning
    }, work_items)
    
    return decision
```
