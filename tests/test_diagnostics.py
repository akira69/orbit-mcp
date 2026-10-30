import json
import subprocess
import sys


def test_check_reports_invalid_configuration_without_traceback(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orbit_mcp.server",
            "--config",
            str(tmp_path / "missing.toml"),
            "--check",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["checks"]["config"]["ok"] is False
    assert "Traceback" not in result.stderr


def test_check_verifies_mcp_and_initial_commits(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    fake = tmp_path / "orbit"
    fake.write_text(f'#!{sys.executable}\nprint("orbit 1.0.0")\n')
    fake.chmod(0o755)
    config = tmp_path / "config.toml"
    config.write_text(
        f"orbit = {json.dumps(str(fake))}\n"
        f"state_dir = {json.dumps(str(tmp_path / 'state'))}\n"
        f"[repositories]\ndemo = {json.dumps(str(repo))}\n"
    )

    def run():
        return subprocess.run(
            [sys.executable, "-m", "orbit_mcp.server", "--config", str(config), "--check"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    first = run()
    assert first.returncode == 1
    failed = json.loads(first.stdout)
    assert "initial commit" in failed["checks"]["repositories"]["error"]
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "init",
        ],
        check=True,
    )
    second = run()
    assert second.returncode == 0, second.stdout + second.stderr
    report = json.loads(second.stdout)
    assert report["ok"] is True
    assert report["checks"]["mcp"]["tools"] == 5
    assert report["checks"]["mcp"]["repository_call"] is True
    assert report["checks"]["orbit"]["version"] == "orbit 1.0.0"
    assert "desktop" in report["scope"]
