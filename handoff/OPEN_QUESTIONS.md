# Open questions for the owner

| ID | Question | Default if unanswered | Blocks |
| --- | --- | --- | --- |
| Q1 | Amend living spec §11 "no background browsing" to allow AFK sessions (objective-scoped, allowlisted, budgeted, proposals-only)? | Keep AFK off and unbuilt | F17 |
| Q2 | Guardian: confirm which actions are ask-first (cleanup, organize, disable startup item, quick scan) vs never (disable Defender/firewall/UAC, System32, registry deletes) | Use the split in F19 | F19 v1 |
| Q3 | "Locker" = secrets vault (assumed), folder locker, or app/PC lock? | Secrets vault | F20 |
| Q4 | First free providers: Gemini AI Studio, Groq, OpenRouter? Order? | Gemini -> Groq -> OpenRouter | F13 |
| Q5 | Assistant name (keep "Aetheris"?) and default tone (casual / formal) | Aetheris, concise-casual | F00 |
| Q6 | You wrote "the best song player and following app, all use cases". Did you mean the best **assistant** / helper app (likely a typo or voice slip), or do you actually want music playback / a social "follow" feature? | Treat as "best assistant app"; no music or social features | Scope |
| Q7 | License: MIT, Apache-2.0, or keep private/proprietary for now? | No license file (all rights reserved) | Public release |
| Q8 | Allow committing `shell/package-lock.json` so UI tests can run in CI with `npm ci`? (Currently forbidden by hygiene tests.) | Keep forbidden; UI CI uses `npm install` | UI CI |
| Q9 | Monetization direction (open core + paid sync, pro tier, or BYOK free forever)? | Decide after v1 pilot | 1.0 |
