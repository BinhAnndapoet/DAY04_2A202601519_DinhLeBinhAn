---
name: think
track: bonus
kind: control
provider: 
requires_env: []
inputs: [reflection]
outputs: [reflection]
side_effect: false
---
# think

Strategic reflection tool. Use it between research steps to deliberately
record: what has been found so far, what is still missing, and the next planned
action. It performs no external lookup and returns the reflection unchanged so
the agent reasons before continuing.

Use only for genuinely multi-step research. Do not call it for a simple,
single-tool request.
