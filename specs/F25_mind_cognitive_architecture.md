# F25: Mind (cognitive architecture)

**Status:** proposed (composition spec; most parts exist as separate subsystems)
**Default:** n/a (describes how existing and proposed parts work together)
**Depends on:** F03, F06, F08, F10, F11, F15, F16, F17, F18

## 1. Purpose

The owner wants Aetheris to feel like a real mind: it notices, wonders, learns, remembers, reflects, and grows. This spec defines that mind as an **engineering composition** of existing subsystems, so "mind" never becomes a vague monolith and every faculty stays measurable and gated.

## 2. Faculties -> subsystems

| Faculty | What it means for the user | Subsystem | Authority |
| --- | --- | --- | --- |
| Perception | Notices tasks, failures, feedback, PC state, new releases | Event memory, watchdog, Guardian T0 | read |
| Attention | Decides what matters now | Task queue priority + curiosity scoring | delegated (queue) |
| Working memory | Holds the current task context | Plan + retrieved lessons in prompt | none |
| Long-term memory | Remembers facts, lessons, you, projects | F06 stores | own stores |
| Reasoning | Thinks before acting, abstains when unsure | F11 | advisory |
| Planning | Breaks goals into steps and DAGs | F03 | plan store |
| Action | Does things in the world | Tools via SafetyLayer | gated |
| Reflection | Asks "why did that fail?" | F10 | verdicts |
| Learning | Keeps only proven improvements | F08, F09, F14 | gated levers |
| Curiosity | Wonders what it is bad at or missing | F16 | objectives only |
| Dreaming / AFK | Studies and experiments while you are away | F17 via F18 | proposals only |
| Metacognition | Knows its own level and limits | F07 scorecard + F21 reports | read |
| Values | Loyal, honest, careful | F00 manners + F04 tiers | enforced |

## 3. The mind loop

```
perceive -> attend -> (reason) -> plan -> act (gated) -> observe
   -> reflect -> remember -> (learn if measured better) -> report
idle: curiosity -> objective -> research/experiment -> proposal -> gate
```

## 4. Rules

- Faculties communicate through typed records (Plan, Deliberation, EvidenceBundle, LearningObjective, Lesson), never shared mutable state.
- Only Action touches the world, only through SafetyLayer.
- Advisory faculties can never gain authority by composition.
- "Growth" is only what the scorecard measures.

## 5. Personality layer (thin)

Tone, name, and style come from the profile (F06) and manners (F00). Personality never changes decisions, only wording.

## 6. Future

- Consolidation pass ("sleep"): merge duplicate lessons, decay low-usefulness memories, gated by retrieval benchmark
- Self-model: a read-only summary of its own capabilities and weak spots, generated from the scorecard, used by curiosity

## 7. Tests

`test_advisory_faculties_hold_no_tool_handles`, `test_personality_does_not_change_plan`, `test_consolidation_preserves_versions`.
