from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..controller.controller import Controller
from ..controller.executive import ExecutiveController
from ..controller.queue import TaskQueue
from ..evaluation.cases import default_suite
from ..evaluation.evaluator import Evaluator
from ..learning.engine import LearningEngine
from ..memory.experience import ExperienceStore
from ..memory.knowledge import KnowledgeStore
from ..memory.learned import LearnedKeywordStore
from ..memory.store import MemoryStore
from ..model import ModelProvider, ModelConfig, build_provider


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

    @classmethod
    def create(cls, root: str = ".aetheris_data") -> "AppState":
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
        learning = LearningEngine(memory, config.workspace_root, knowledge, experience, learned)

        # Build model provider from env config
        model_cfg = ModelConfig.from_env()
        model = build_provider(model_cfg)

        # Controller builds its own model-aware Planner internally
        controller = Controller(
            config,
            model=model,
            learned_store_path=str(base / "learned.jsonl"),
        )

        def improve() -> bool:
            """One improvement cycle: run the full benchmark then attempt one learning step."""
            result = learning.attempt(default_suite())
            # Propagate freshly learned keywords into the live controller's planner.
            if result.accepted:
                controller.planner = controller.planner.__class__(
                    extra_keywords=learning.extra_keywords,
                    model=model,
                    registry_tools=tuple(controller.registry.list()),
                )
            return result.accepted

        executive = ExecutiveController(
            config,
            queue,
            memory,
            controller=controller,
            improve_fn=improve,
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
        )
