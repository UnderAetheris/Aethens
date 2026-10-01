# Architecture overview

Visual summary. The authoritative detail is in `architecture/ARCHITECTURE_BASELINE.md` and the living spec.

## The spine

```mermaid
flowchart LR
  U[Owner / Chat / Queue] --> C[Controller / Executive]
  C --> P[Planner]
  P -->|Plan| C
  C --> S{{SafetyLayer\nsingle execution gate}}
  S -->|allowed| T[Tools]
  S -->|blocked / dry-run| M
  T --> M[(Event Memory)]
  C --> M
```

## Advisors (read-only, no authority)

```mermaid
flowchart TB
  R[ReasoningEngine] -.advice.-> P[Planner]
  R -.advice.-> RF[Reflection]
  R -.advice.-> L[Learning]
  UN[RepoUnderstanding] -.facts.-> RF
  RE[ResearchEngine] -.EvidenceBundle.-> R
  RE --> NP{{NetworkPerimeter\nsingle egress gate}}
  NP --> WEB[(Allowlisted HTTPS)]
  CU[Curiosity F16] -.objectives.-> EX[Executive idle hook]
```

## The improvement loop

```mermaid
flowchart LR
  E[Evaluator\nfrozen benchmarks] -->|failures| L[Learning Engine]
  L -->|one candidate| TR[Trial in sandbox]
  TR --> E2[Re-evaluate all suites]
  E2 -->|better + 0 regressions| A[Accept\nreceipt + knowledge]
  E2 -->|else| RB[Discard / rollback]
  A --> E
```

## Unattended / AFK

```mermaid
stateDiagram-v2
  [*] --> Idle
  Idle --> Check: tick
  Check --> Step: healthy + bounded + work ready
  Check --> Paused: unhealthy or ambiguous
  Step --> Checkpoint
  Checkpoint --> Idle
  Paused --> StopForReview: unrecoverable
  Paused --> Idle: human resumes
```

## Boundaries

| Side effect | Sole owner |
| --- | --- |
| Execute tool | `SafetyLayer.run()` |
| Network (research) | `NetworkPerimeter.fetch()` |
| Network (models) | `network_egress.model_provider` |
| Persistence | owned append-only stores |
| Patch validation | throwaway sandbox |
