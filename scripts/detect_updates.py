#!/usr/bin/env python3
"""Detect new versions of configured pipelines and report them as a matrix."""

import argparse
import json
import subprocess
from enum import Enum
from pathlib import Path

import yaml
from packaging.version import InvalidVersion, Version

# keys in pipeline info file
PIPELINES_KEY = "pipelines"
NAME_KEY = "name"
REPO_KEY = "github-repo"
VERSION_SOURCE_KEY = "version-source"
EXISTING_VERSIONS_KEY = "existing-versions"

# additional key in output file
VERSION_KEY = "version"


class VersionSource(str, Enum):
    """Version source choices."""

    TAGS = "tags"
    RELEASES = "releases"


def _validate_pipeline_info(pipeline):
    """Validate the pipeline info dictionary."""
    missing_keys = []
    for required_key in [NAME_KEY, REPO_KEY, VERSION_SOURCE_KEY, EXISTING_VERSIONS_KEY]:
        if required_key not in pipeline:
            missing_keys.append(required_key)
    if missing_keys:
        raise ValueError(
            f"Missing required keys {missing_keys} in pipeline info: {pipeline}."
        )


def _fetch_versions(repo, version_source):
    """Fetch the available versions of a pipeline repository."""
    match version_source:
        case VersionSource.TAGS:
            endpoint = f"repos/{repo}/tags"
            query = ".[].name"
        case VersionSource.RELEASES:
            endpoint = f"repos/{repo}/releases"
            query = ".[].tag_name"
        case _:
            raise ValueError(
                f"Unknown version source: {version_source}."
                f" Valid choices are: {[e.value for e in VersionSource]}"
            )

    result = subprocess.run(
        ["gh", "api", "--paginate", endpoint, "--jq", query],
        capture_output=True,
        text=True,
        check=True,
    )

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _parse_version(raw_version):
    """Parse a version string into a comparable version object."""
    try:
        return Version(raw_version)
    except InvalidVersion:
        return None


def _get_latest_existing_version(pipeline):
    """Get the last checked version from the pipeline info."""
    existing_versions = filter(
        None, [_parse_version(v) for v in pipeline[EXISTING_VERSIONS_KEY]]
    )
    if not existing_versions:
        return None
    return max(existing_versions)


def _build_version_entries(raw_versions):
    """Build sorted version entries, optionally excluding pre-releases."""
    version_entries = []
    for raw in raw_versions:
        parsed = _parse_version(raw)
        if parsed is None:
            continue
        if parsed.is_prerelease:
            continue
        version_entries.append((parsed, raw))
    version_entries.sort(key=lambda entry: entry[0])
    return version_entries


def _write_matrix_output(matrix_entries, output_path):
    """Write the matrix to the workflow output."""
    matrix_json = json.dumps(matrix_entries)
    with open(output_path, "a") as output_file:
        output_file.write(f"matrix={matrix_json}\n")


def _get_matrix_entries(pipeline):
    """Get the matrix entries for a pipeline."""
    repo = pipeline[REPO_KEY]
    version_source = pipeline.get(VERSION_SOURCE_KEY)
    version_entries = _build_version_entries(_fetch_versions(repo, version_source))

    if not version_entries:
        raise RuntimeError(f"No versions found for repo {repo!r}.")

    latest_existing_version = _get_latest_existing_version(pipeline)
    if latest_existing_version is None:
        new_versions = version_entries[-1:]
    else:
        new_versions = [
            (version, raw)
            for version, raw in version_entries
            if version > latest_existing_version
        ]

    if not new_versions:
        return

    for _, raw in new_versions:
        matrix_entry = pipeline.copy()
        matrix_entry[VERSION_KEY] = str(raw)
        yield matrix_entry


def detect_updates(config_path, output_path):
    """Detect new versions of pipelines and write a job matrix file."""
    config = yaml.safe_load(config_path.read_text())
    try:
        pipelines = config[PIPELINES_KEY]
    except KeyError:
        raise ValueError(
            f"{config_path} file must have a top-level {PIPELINES_KEY:!r} key."
        )
    matrix_entries = []

    for pipeline in pipelines:
        _validate_pipeline_info(pipeline)
        matrix_entries.extend(_get_matrix_entries(pipeline))

    _write_matrix_output(matrix_entries, output_path)


def _build_parser():
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Detect new versions of pipelines and report them as a matrix."
    )
    parser.add_argument(
        "config_path",
        type=Path,
        help="Path to the pipeline info YAML file.",
    )
    parser.add_argument(
        "output_path",
        type=Path,
        help="Path to the output file where the job matrix will be written.",
    )
    return parser


def main():
    """Run the update detection for all configured pipelines."""
    parser = _build_parser()
    args = parser.parse_args()
    detect_updates(args.config_path, args.output_path)


if __name__ == "__main__":
    main()
