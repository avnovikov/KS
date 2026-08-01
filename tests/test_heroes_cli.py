from ks.heroes.cli import main


def test_cli_dry_run(capsys):
    code = main(["collect", "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "roster cells: 16" in out
    assert "skill slots: 6" in out


def test_cli_bad_config(tmp_path, capsys):
    bad = tmp_path / "missing.yaml"
    code = main(["collect", "--config", str(bad), "--dry-run"])
    assert code == 1
    err = capsys.readouterr().err
    assert "Error loading config" in err
