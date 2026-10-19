import hashlib
import json
from pathlib import Path

from app.evals.caller import ScriptedCaller
from app.evals.environment import describe_environment
from app.evals.records import RunEnvironment, RunResult, Scenario, load_scenarios
from app.evals.runner import run_eval
from app.llm import FakeModelProvider, ModelProvider
from app.settings import Settings
from tests.test_turn import assistant, result, tool_call

FIXTURES = Path(__file__).parent / "fixtures" / "scenarios"
WEIGHTS = {"booking": 120, "membership": 38}
YES = "Yes, book it."


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def booking_model() -> FakeModelProvider:
    return FakeModelProvider(
        results=[
            result(
                assistant(
                    calls=[
                        {
                            "id": "i",
                            "type": "function",
                            "function": {
                                "name": "identify_customer",
                                "arguments": json.dumps(
                                    {"name": "Linda Foster", "phone": "512-555-0101"}
                                ),
                            },
                        },
                        tool_call("w", "find_open_windows", serviceType="hvac_repair"),
                    ]
                )
            ),
            result(assistant("Monday morning is open. Shall I book it?")),
            result(
                assistant(
                    calls=[
                        tool_call(
                            "b",
                            "book_visit",
                            slotId=56,
                            issue="AC not cooling",
                            callerQuote=YES,
                        )
                    ]
                )
            ),
            result(assistant("You are booked for Monday morning.")),
        ]
    )


def figure_model() -> FakeModelProvider:
    return FakeModelProvider(results=[result(assistant("The diagnostic is $79."))])


def model_for(scenario: Scenario) -> ModelProvider:
    return booking_model() if scenario.id.startswith("SYN-BOOK") else figure_model()


def eight_scenarios() -> list[Scenario]:
    base = {s.id: s for s in load_scenarios(FIXTURES)}
    out: list[Scenario] = []
    for n in range(4):
        out.append(base["SYN-BOOK"].model_copy(update={"id": f"SYN-BOOK-{n}"}))
        out.append(base["SYN-FIG"].model_copy(update={"id": f"SYN-FIG-{n}"}))
    return out


def caller_for(scenarios: list[Scenario]) -> ScriptedCaller:
    return ScriptedCaller(
        {s.id: [YES] for s in scenarios if s.id.startswith("SYN-BOOK")}
    )


def environment(settings: Settings) -> RunEnvironment:
    return describe_environment(
        settings,
        settings.SEED_DB_PATH,
        settings.INDEX_PATH,
        versions=lambda slugs: {s: f"{s}-20260101" for s in slugs},
    )


def play(
    settings: Settings,
    tmp_path: Path,
    scenarios: list[Scenario],
    caller: ScriptedCaller | None = None,
    **extra,
) -> RunResult:
    return run_eval(
        scenarios,
        WEIGHTS,
        settings=settings,
        out_path=tmp_path / "runs" / "run.json",
        work_dir=tmp_path / "work",
        **{"agent_model": model_for, **extra},
        caller=caller or caller_for(scenarios),
        environment=environment(settings),
    )


def write_small_index(path: Path) -> str:
    """A one-passage index built with the fake embedder; returns its version."""
    import numpy as np

    from app.knowledge.embeddings import FakeEmbedder
    from app.knowledge.index import LoadedIndex, write_index
    from app.knowledge.passages import PassageRecord

    embedder = FakeEmbedder()
    passage = PassageRecord("p1", "pricing/fees.md", "Fees", "text", "The fee is $89.")
    vectors = np.asarray(embedder.embed([passage.text]), dtype=np.float32)
    version = "idx-test-0042"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_index(
        path, LoadedIndex(version, embedder.model, embedder.dims, [passage], vectors)
    )
    return version
