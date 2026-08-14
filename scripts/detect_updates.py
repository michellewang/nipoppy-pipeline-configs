"""Detect new versions of configured pipelines and report them as a matrix."""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from packaging.version import InvalidVersion, Version

CONFIG_PATH = Path(__file__).resolve().parents[1] / "pipelines.yml"
PIPELINES_KEY = "pipelines"
NAME_KEY = "name"
REPO_KEY = "repo"
VERSION_SOURCE_KEY = "version_source"
INCLUDE_PRERELEASES_KEY = "include_prereleases"
LAST_VERSION_CHECKED_KEY = "last_version_checked"
DEFAULT_VERSION_SOURCE = "releases"
DEFAULT_INCLUDE_PRERELEASES = False
MAX_MATRIX_ENTRIES = 256
GITHUB_OUTPUT_PATH = os.environ.get("GITHUB_OUTPUT")


def fetch_versions(repo, version_source):
    """Fetch the available versions of a pipeline repository."""
    if version_source == "tags":
        endpoint = f"repos/{repo}/tags"
        query = ".[].name"
    else:
        endpoint = f"repos/{repo}/releases"
        query = ".[].tag_name"
    result = subprocess.run(
        ["gh", "api", "--paginate", endpoint, "--jq", query],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def parse_version(raw_version):
    """Parse a version string into a comparable version object."""
    stripped = raw_version[1:] if raw_version.startswith("v") else raw_version
    try:
        return Version(stripped)
    except InvalidVersion:
        return None


def build_version_entries(raw_versions, include_prereleases):
    """Build sorted version entries, optionally excluding pre-releases."""
    version_entries = []
    for raw in raw_versions:
        parsed = parse_version(raw)
        if parsed is None:
            continue
        if parsed.is_prerelease and not include_prereleases:
            continue
        version_entries.append((parsed, raw))
    version_entries.sort(key=lambda entry: entry[0])
    return version_entries


def write_matrix_output(matrix_entries):
    """Publish the matrix to the workflow output."""
    matrix_json = json.dumps(matrix_entries)
    if GITHUB_OUTPUT_PATH:
        with open(GITHUB_OUTPUT_PATH, "a") as file_handle:
            file_handle.write(f"matrix={matrix_json}\n")
    else:
        print(matrix_json)


def main():
    """Run the update detection for all configured pipelines."""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    pipelines = config[PIPELINES_KEY]
    matrix_entries = []
    config_changed = False
    for pipeline in pipelines:
        repo = pipeline[REPO_KEY]
        version_source = pipeline.get(VERSION_SOURCE_KEY, DEFAULT_VERSION_SOURCE)
        include_prereleases = pipeline.get(
            INCLUDE_PRERELEASES_KEY, DEFAULT_INCLUDE_PRERELEASES
        )
        version_entries = build_version_entries(
            fetch_versions(repo, version_source), include_prereleases
        )
        if not version_entries:
            continue
        newest_version, newest_raw = version_entries[-1]
        last_checked = parse_version(pipeline.get(LAST_VERSION_CHECKED_KEY))
        if last_checked is None:
            pipeline[LAST_VERSION_CHECKED_KEY] = newest_raw
            config_changed = True
            continue
        new_versions = [
            (version, raw) for version, raw in version_entries if version > last_checked
        ]
        if not new_versions:
            continue
        for version, raw in new_versions:
            matrix_entries.append(
                {
                    "pipeline": pipeline[NAME_KEY],
                    "repo": repo,
                    "version": str(version),
                }
            )
        pipeline[LAST_VERSION_CHECKED_KEY] = newest_raw
        config_changed = True
    if config_changed:
        with CONFIG_PATH.open("w") as file_handle:
            yaml.safe_dump(config, file_handle, sort_keys=False)
    if len(matrix_entries) > MAX_MATRIX_ENTRIES:
        matrix_entries = matrix_entries[-MAX_MATRIX_ENTRIES:]
        sys.stderr.write(f"Truncated matrix to {MAX_MATRIX_ENTRIES} entries\n")
    write_matrix_output(matrix_entries)


if __name__ == "__main__":
    main()
