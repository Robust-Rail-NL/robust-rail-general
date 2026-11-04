"""Tests for the per-cluster SLURM settings: the SIF_CACHE_DIR override in
docker_utils and the scripts/slurm/site/*.env files the sbatch scripts source."""

import subprocess
from pathlib import Path

from scripts import docker_utils

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "scripts" / "slurm" / "site"


def test_default_sif_cache_dir_is_home_apptainer_images(monkeypatch):
    monkeypatch.delenv("SIF_CACHE_DIR", raising=False)
    assert docker_utils.default_sif_cache_dir() == Path.home() / "apptainer-images"


def test_default_sif_cache_dir_empty_env_falls_back(monkeypatch):
    monkeypatch.setenv("SIF_CACHE_DIR", "")
    assert docker_utils.default_sif_cache_dir() == Path.home() / "apptainer-images"


def test_default_sif_cache_dir_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SIF_CACHE_DIR", str(tmp_path))
    assert docker_utils.default_sif_cache_dir() == tmp_path


def _source(site: str, tmp_path: Path, **env) -> dict[str, str]:
    """Source a site file in a clean bash and return the variables it exports."""
    names = ["SBATCH_ACCOUNT", "SBATCH_PARTITION", "PYTHON_MODULE", "SIF_CACHE_DIR",
             "APPTAINER_CACHEDIR", "APPTAINER_TMPDIR", "XDG_CACHE_HOME"]
    script = f'source "{SITE_DIR / (site + ".env")}"; ' + "; ".join(
        f'echo "{n}=${{{n}-}}"' for n in names)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True,
                         env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", **env}).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


def test_delftblue_site_keeps_the_sbatch_script_defaults(tmp_path):
    got = _source("delftblue", tmp_path)
    assert got["SBATCH_ACCOUNT"] == "research-eemcs-st"
    assert got["SBATCH_PARTITION"] == "compute-p1"
    assert got["PYTHON_MODULE"] == "python/3.13.18"
    assert got["SIF_CACHE_DIR"] == ""  # docker_utils' ~/apptainer-images default applies


def test_the_sbatch_scripts_carry_the_same_delftblue_defaults_as_the_site_file():
    for name in ("generate_scenarios", "run_experiment_array", "aggregate"):
        text = (ROOT / "scripts" / "slurm" / f"{name}.sbatch").read_text()
        assert "#SBATCH --account=research-eemcs-st" in text
        assert "#SBATCH --partition=compute-p1" in text


def test_daic_site_puts_caches_under_linuxhome_not_home(tmp_path):
    got = _source("daic", tmp_path)
    base = tmp_path / "linuxhome"
    assert got["SBATCH_ACCOUNT"] == "daic-eemcs-st-algor"
    assert got["SBATCH_PARTITION"] == "daic-eemcs-st"
    assert got["PYTHON_MODULE"] == "python/3.13.12"
    for name in ("SIF_CACHE_DIR", "APPTAINER_CACHEDIR", "APPTAINER_TMPDIR", "XDG_CACHE_HOME"):
        assert Path(got[name]).is_relative_to(base), name
        assert Path(got[name]).is_dir(), name


def test_site_files_do_not_override_values_exported_beforehand(tmp_path):
    got = _source("daic", tmp_path, SBATCH_ACCOUNT="someone-else", SIF_CACHE_DIR="/elsewhere/sif")
    assert got["SBATCH_ACCOUNT"] == "someone-else"
    assert got["SIF_CACHE_DIR"] == "/elsewhere/sif"
