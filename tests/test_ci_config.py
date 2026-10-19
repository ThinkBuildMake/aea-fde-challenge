import yaml

from tests.conftest import REPO

WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"


def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))  # YAML reads a bare `on` as True


def test_gate_runs_on_every_branch_push_and_pull_request():
    on = triggers(load())
    assert on["push"]["branches"] == ["**"]
    assert "pull_request" in on


def test_gate_job_checks_out_full_history_and_runs_make_gate():
    steps = load()["jobs"]["gate"]["steps"]
    checkout = next(
        s for s in steps if s.get("uses", "").startswith("actions/checkout")
    )
    assert checkout["with"]["fetch-depth"] == 0
    assert any(s.get("run") == "make gate" for s in steps)


def test_deploy_needs_the_gate_and_runs_only_for_build_meridian_pushes():
    deploy = load()["jobs"]["deploy"]
    assert "gate" in deploy["needs"]
    condition = deploy["if"]
    assert "github.event_name == 'push'" in condition
    assert "refs/heads/build/meridian" in condition


def test_workflow_holds_no_literal_token():
    text = WORKFLOW.read_text()
    assert "${{ secrets.RAILWAY_TOKEN }}" in text
    assert "sk-" not in text


def test_dependabot_watches_python_and_actions():
    config = yaml.safe_load((REPO / ".github" / "dependabot.yml").read_text())
    assert {u["package-ecosystem"] for u in config["updates"]} == {
        "uv",
        "github-actions",
    }


def test_railway_token_is_set_only_on_the_railway_up_step():
    deploy = load()["jobs"]["deploy"]
    assert "RAILWAY_TOKEN" not in deploy.get("env", {})
    holders = [s for s in deploy["steps"] if "RAILWAY_TOKEN" in s.get("env", {})]
    assert [s["run"].split()[0:2] for s in holders] == [["railway", "up"]]
