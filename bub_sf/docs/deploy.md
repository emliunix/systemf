# Deployment with Auto-Rollback

## Overview

The project should support a deployment process that runs as a deployed package, with an **auto-rollback mechanism** to ensure reliability on release.

## Deployment Process

1. Build and release a new version of the package.
2. Deploy the new version to the target environment.
3. The agent restarts with the new version after a release.

## Auto-Rollback Mechanism

After the agent restarts post-release, it must perform a **self-check**:

1. **Self-check**: The agent runs a health/validation routine to verify it is functioning correctly (e.g., can connect to required services, can process a test message, core subsystems are responsive).
2. **Mark success**: If the self-check passes, the agent marks the deployment as successful within the release pipeline.
3. **Hard timeout**: There is a hard timeout window in the release pipeline. If the agent does not mark success before this timeout expires, it is considered a failed deployment.
4. **Rollback**: On timeout (no success mark) or explicit failure, the release pipeline automatically triggers a rollback to the previous known-good version.

## Key Requirements

- The release pipeline must track deployment status and enforce the hard timeout.
- The agent self-check must be fast but comprehensive enough to catch common failure modes.
- Rollback should be automatic and require no manual intervention.
- Previous versions must be retained to enable quick rollback.

## Open Questions

- What specific checks should the self-check include?
- What is the appropriate hard timeout duration?
- How should deployment status be communicated (file marker, API call, signal)?
