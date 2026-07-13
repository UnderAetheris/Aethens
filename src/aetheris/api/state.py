from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..config import (
    Config,
    PromotionConfig,
    resolve_reasoning_enabled,
    resolve_research_enabled,
    resolve_unattended_enabled,
)
from ..controller.controller import Controller
from ..controller.executive import ExecutiveController
from ..controller.queue import TaskQueue
from ..evaluation.cases import default_suite
from ..learning.autonomous import AutonomousLoop
from ..learning.engine import LearningEngine
from ..learning.plan_review import PlanReviewQueue
from ..memory.experience import ExperienceStore
from ..memory.knowledge import KnowledgeStore
from ..memory.learned import LearnedKeywordStore
from ..memory.store import MemoryStore
from ..model import ModelProvider, ModelConfig, build_provider
from ..reasoning.engine import ReasoningEngine
from ..research import ALLOWLIST, NetworkPerimeter, ResearchEngine, ResearchJournal
from ..skills.idle_promotion import IdleSkillPromotion
from ..skills.registry import SkillRegistry
from ..understanding.engine import RepoUnderstanding
from ..unattended import (
    HealthWatchdog,
    SessionBounds,
    SessionJournal,
    UnattendedSupervisor,
    build_sampler,
)


@dataclass
class AppState:
    """Owns the wired engine singletons. One per app instance."""

    config: Config
    memory: MemoryStore
    queue: TaskQueue
    knowledge: KnowledgeStore
    experience: ExperienceStore
    learned: LearnedKeywordStore
    learning: LearningEngine
    executive: ExecutiveController
    model: ModelProvider | None = None
    plan_review: PlanReviewQueue | None = None
    autonomous: AutonomousLoop | None = None
    registry: SkillRegistry | None = None
    promotion_config: PromotionConfig | None = None
    understanding: RepoUnderstanding | None = None
    reasoning: ReasoningEngine | None = None
    research: ResearchEngine | None = None
    unattended: UnattendedSupervisor | None = None

    @classmethod
    def create(
        cls,
        root: str = ".aetheris_data",
        idle_promotion: IdleSkillPromotion | None = None,
        config: Config | None = None,
        env: Mapping[str, str] | None = None,
    ) -> "AppState":
        base = Path(root)
        base.mkdir(parents=True, exist_ok=True)
        if config is None:
            config = Config(
                log_path=str(base / "events.jsonl"),
                workspace_root=str(base / "workspace"),
            )
        else:
            # Honor the provided reasoning/safety settings but keep I/O scoped
            # to this root so tests and ops never scan/overwrite the project.
            config = Config(
                safe_mode=config.safe_mode,
                log_path=str(base / "events.jsonl"),
                workspace_root=str(base / "workspace"),
                allowed_shell_commands=config.allowed_shell_commands,
                reflection_enabled=config.reflection_enabled,
                code_loop_enabled=config.code_loop_enabled,
                reasoning_enabled=config.reasoning_enabled,
                research_enabled=config.research_enabled,
            )
        Path(config.workspace_root).mkdir(parents=True, exist_ok=True)
        reasoning_enabled = resolve_reasoning_enabled(config, env if env is not None else os.environ)
        research_enabled = resolve_research_enabled(config, env if env is not None else os.environ)
        unattended_enabled = resolve_unattended_enabled(config, env if env is not None else os.environ)

        memory = MemoryStore(config.log_path)
        queue = TaskQueue(str(base / "queue.jsonl"), memory)
        knowledge = KnowledgeStore(str(base / "knowledge.jsonl"))
        experience = ExperienceStore(str(base / "experience.jsonl"))
        learned = LearnedKeywordStore(str(base / "learned.jsonl"))

        registry = SkillRegistry(str(base / "skills.jsonl"))
        learning = LearningEngine(memory, config.workspace_root, knowledge, experience, learned)
        autonomous = AutonomousLoop(
            memory, config.workspace_root, knowledge, experience, learned, registry
        )

        model_cfg = ModelConfig.from_env()
        model = build_provider(model_cfg)

        from ..planner.planner import Planner

        controller = Controller(
            config,
            model=model,
            learned_store_path=str(base / "learned.jsonl"),
        )
        controller.planner = Planner(
            learned_store_path=str(base / "learned.jsonl"),
            model=model,
            registry_tools=tuple(controller.registry.list()),
            skills=registry,
        )

        def improve() -> bool:
            result = learning.attempt(default_suite())
            if result.accepted:
                controller.planner = controller.planner.__class__(
                    extra_keywords=learning.extra_keywords,
                    model=model,
                    registry_tools=tuple(controller.registry.list()),
                )
            return result.accepted

        promotion_config = PromotionConfig.from_env()

        understanding = RepoUnderstanding(
            root=config.workspace_root,
            model_path=str(base / "repo_model.json"),
        )

        reasoning = ReasoningEngine(
            understanding=understanding,
            memory=memory,
            skills=registry,
        ) if reasoning_enabled else None

        # Research Engine: the network boundary. Default-on (earned by the
        # expanded gate). When disabled, `research` is None and the
        # NetworkPerimeter is never constructed -- the boundary is fully sealed,
        # byte-identical to the non-research floor.
        research = None
        if research_enabled:
            research_journal = ResearchJournal(str(base / "research.journal"))
            research_perimeter = NetworkPerimeter(ALLOWLIST)
            research = ResearchEngine(
                allowlist=ALLOWLIST,
                perimeter=research_perimeter,
                journal=research_journal,
            )

        executive = ExecutiveController(
            config,
            queue,
            memory,
            controller=controller,
            improve_fn=improve,
            skill_promotion=idle_promotion,
            promotion_budget=promotion_config.promotion_budget,
            promotion_config=promotion_config,
            understanding=understanding,
            reasoning=reasoning,
        )

        plan_review = PlanReviewQueue()

        # Unattended Supervisor: a bounded, fail-closed brake. Default-OFF.
        # When on, it *composes* the existing executive in a bounded session; it
        # adds no authority, no execution path, no budget widening. When off it is
        # None and the executive runs exactly as today (byte-identical off-path).
        unattended = None
        if unattended_enabled:
            u_journal = SessionJournal(
                str(base / "unattended.journal.jsonl"),
                str(base / "unattended.snapshot.json"),
            )
            u_sampler = build_sampler(executive, research)
            u_watchdog = HealthWatchdog(u_sampler)
            u_bounds = SessionBounds(
                max_wall_clock_s=3600.0,
                max_steps=10000,
                max_consecutive_failures=3,
                max_ticks_without_progress=200,
            )
            unattended = UnattendedSupervisor(
                executive, u_watchdog, u_journal, u_bounds
            )

        return cls(
            config=config,
            memory=memory,
            queue=queue,
            knowledge=knowledge,
            experience=experience,
            learned=learned,
            learning=learning,
            executive=executive,
            model=model,
            plan_review=plan_review,
            autonomous=autonomous,
            registry=registry,
            promotion_config=promotion_config,
            understanding=understanding,
            reasoning=reasoning,
            research=research,
            unattended=unattended,
        )
