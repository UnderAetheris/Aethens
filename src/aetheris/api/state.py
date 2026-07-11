from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Config, PromotionConfig
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
from ..skills.idle_promotion import IdleSkillPromotion
from ..skills.promoter import SkillPromoter
from ..skills.registry import SkillRegistry
from ..understanding.engine import RepoUnderstanding


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

    @classmethod
    def create(cls, root: str = ".aetheris_data", idle_promotion: IdleSkillPromotion | None = None) -> "AppState":
        base = Path(root)
        base.mkdir(parents=True, exist_ok=True)
        config = Config(
            log_path=str(base / "events.jsonl"),
            workspace_root=str(base / "workspace"),
        )
        Path(config.workspace_root).mkdir(parents=True, exist_ok=True)

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
        ) if config.reasoning_enabled else None

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
        )
