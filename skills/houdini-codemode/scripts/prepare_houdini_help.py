from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path


ARCHIVES_TO_EXTRACT = [
    "anim",
    "assets",
    "character",
    "dyno",
    "finiteelements",
    "fur",
    "hapi",
    "help",
    "hom",
    "hqueue",
    "io",
    "model",
    "mplay",
    "news",
    "nodes",
    "network",
    "shelf",
    "tops",
    "vex",
    "visualizers",
    "commands",
    "ref",
    "crowds",
    "destruction",
    "dopparticles",
    "expressions",
    "feathers",
    "fluid",
    "muscles",
    "ocean",
    "pyro",
    "solaris",
    "vellum",
]

DIRECTORIES_TO_COPY = [
    "copernicus",
    "heightfields",
    "heightfields_cop",
    "hwebserver",
    "ml",
    "mpm",
]

ROOT_FILES_TO_COPY = [
    "_settings.ini",
    "_wip.txt",
    "credits.txt",
    "education.txt",
    "find.txt",
    "index.txt",
]

TEXT_SUFFIXES = {
    ".ini",
    ".json",
    ".log",
    ".md",
    ".pypanel",
    ".py",
    ".txt",
    ".ui",
    ".xml",
}


@dataclass
class PreparedItem:
    kind: str
    source: str
    destination: str
    file_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a local Houdini help corpus for skill-side lookup."
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Raw Houdini help folder. Defaults to <skill>/help",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Prepared output folder. Defaults to <skill>/references/help_prepared",
    )
    return parser.parse_args()


def count_files(path: Path) -> int:
    if path.is_file():
        return 1
    return sum(1 for child in path.rglob("*") if child.is_file())


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    if not path.is_dir():
        raise SystemExit(f"{label} is not a directory: {path}")


def copy_tree_filtered(source: Path, destination: Path) -> int:
    file_count = 0
    for src_file in source.rglob("*"):
        if not src_file.is_file():
            continue
        if src_file.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel_path = src_file.relative_to(source)
        dest_file = destination / rel_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dest_file)
        file_count += 1
    return file_count


def extract_zip(source_zip: Path, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_zip) as archive:
        archive.extractall(destination)
    return count_files(destination)


def copy_file(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return 1


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    skill_root = script_dir.parent
    source_root = Path(args.source).resolve() if args.source else (skill_root / "help").resolve()
    output_root = Path(args.output).resolve() if args.output else (skill_root / "references" / "help_prepared").resolve()
    temp_root = output_root.with_name(output_root.name + "_tmp")

    ensure_exists(source_root, "Source help folder")

    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    manifests_root = temp_root / "manifests"

    prepared_items: list[PreparedItem] = []
    skipped = {
        "missing_archives": [],
        "missing_directories": [],
        "missing_root_files": [],
        "excluded_top_level_entries": [],
    }

    included_top_level_names = set()

    for archive_name in ARCHIVES_TO_EXTRACT:
        zip_path = source_root / f"{archive_name}.zip"
        if not zip_path.exists():
            skipped["missing_archives"].append(f"{archive_name}.zip")
            continue
        destination = temp_root / archive_name
        file_count = extract_zip(zip_path, destination)
        prepared_items.append(
            PreparedItem(
                kind="archive",
                source=str(zip_path.relative_to(source_root)),
                destination=str(destination.relative_to(temp_root)),
                file_count=file_count,
            )
        )
        included_top_level_names.add(zip_path.name)

    for directory_name in DIRECTORIES_TO_COPY:
        source_dir = source_root / directory_name
        if not source_dir.exists():
            skipped["missing_directories"].append(directory_name)
            continue
        destination = temp_root / directory_name
        file_count = copy_tree_filtered(source_dir, destination)
        prepared_items.append(
            PreparedItem(
                kind="directory",
                source=str(source_dir.relative_to(source_root)),
                destination=str(destination.relative_to(temp_root)),
                file_count=file_count,
            )
        )
        included_top_level_names.add(directory_name)

    for file_name in ROOT_FILES_TO_COPY:
        source_file = source_root / file_name
        if not source_file.exists():
            skipped["missing_root_files"].append(file_name)
            continue
        destination = temp_root / file_name
        file_count = copy_file(source_file, destination)
        prepared_items.append(
            PreparedItem(
                kind="root_file",
                source=str(source_file.relative_to(source_root)),
                destination=str(destination.relative_to(temp_root)),
                file_count=file_count,
            )
        )
        included_top_level_names.add(file_name)

    for child in sorted(source_root.iterdir(), key=lambda p: p.name.lower()):
        if child.name in included_top_level_names:
            continue
        skipped["excluded_top_level_entries"].append(
            {
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
            }
        )

    summary = {
        "source_root": str(source_root),
        "output_root": str(output_root),
        "archives_requested": ARCHIVES_TO_EXTRACT,
        "directories_requested": DIRECTORIES_TO_COPY,
        "root_files_requested": ROOT_FILES_TO_COPY,
        "prepared_items": [item.__dict__ for item in prepared_items],
        "prepared_item_count": len(prepared_items),
        "prepared_file_count": sum(item.file_count for item in prepared_items),
    }

    write_json(manifests_root / "summary.json", summary)
    write_json(manifests_root / "sources.json", [item.__dict__ for item in prepared_items])
    write_json(manifests_root / "skipped.json", skipped)

    if output_root.exists():
        shutil.rmtree(output_root)
    temp_root.replace(output_root)

    print(
        json.dumps(
            {
                "ok": True,
                "source_root": str(source_root),
                "output_root": str(output_root),
                "prepared_item_count": len(prepared_items),
                "prepared_file_count": sum(item.file_count for item in prepared_items),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
