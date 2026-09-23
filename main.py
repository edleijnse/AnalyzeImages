import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set

# Standardverzeichnisse gemäß Aufgabenstellung
DEFAULT_SOURCE_DIR = r"D:\AnalyzeImages"
DEFAULT_TARGET_DIR = r"D:\CleanedImages"

# Unterstützte Bildformate
DEFAULT_IMAGE_EXTENSIONS: Set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".heic",
    ".raw",
    ".cr2",
    ".nef",
    ".arw",
    ".dng",
}


@dataclass
class CopyStats:
    """Statistiken über den Kopiervorgang."""

    total_files_scanned: int = 0
    copied_count: int = 0
    skipped_existing_count: int = 0
    skipped_dot_files_count: int = 0
    skipped_dot_dirs_count: int = 0
    skipped_converted_dirs_count: int = 0
    skipped_non_image_files_count: int = 0


def is_dot_file_or_dir(name: str) -> bool:
    """Prüft, ob ein Datei- oder Ordnername mit einem Punkt (.) beginnt."""
    return name.startswith(".")


def is_converted_dir(dir_name: str) -> bool:
    """
    Prüft, ob es sich um ein 'Converted'-Verzeichnis handelt.
    Erfasst Ordner wie 'Converted', 'Converted PS', 'converted PS', 'Converted by PS' etc.
    """
    return "converted" in dir_name.lower()


def is_image_file(file_name: str, extensions: Optional[Set[str]] = None) -> bool:
    """Prüft anhand der Dateiendung, ob es sich um eine Bilddatei handelt."""
    valid_exts = extensions if extensions is not None else DEFAULT_IMAGE_EXTENSIONS
    return Path(file_name).suffix.lower() in valid_exts


def copy_cleaned_images(
    source_dir: Path | str,
    target_dir: Path | str,
    extensions: Optional[Set[str]] = None,
    only_images: bool = True,
    overwrite: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
) -> CopyStats:
    """
    Kopiert Bilddateien aus source_dir nach target_dir unter Beibehaltung der Verzeichnisstruktur.

    Filterkriterien:
    - Verzeichnisse und Dateien, die mit einem Punkt (.) beginnen, werden ignoriert.
    - Unterverzeichnisse, die 'Converted' im Namen tragen, werden nicht kopiert.
    - Standardmäßig werden nur Bilddateien berücksichtigt.
    """
    src_path = Path(source_dir).resolve()
    dst_path = Path(target_dir).resolve()

    if not src_path.exists():
        raise FileNotFoundError(f"Quellverzeichnis existiert nicht: {src_path}")

    stats = CopyStats()

    if verbose:
        mode_text = " [TROCKENLAUF / DRY RUN]" if dry_run else ""
        print("=" * 60)
        print(f"Starte Bereinigung und Kopiervorgang{mode_text}")
        print(f"Quelle: {src_path}")
        print(f"Ziel:   {dst_path}")
        print("=" * 60)

    for root, dirs, files in os.walk(src_path):
        current_dir = Path(root)

        # Unterordner filtern (in-place Modifikation von dirs verhindert das Betreten)
        filtered_dirs = []
        for d in dirs:
            if is_dot_file_or_dir(d):
                stats.skipped_dot_dirs_count += 1
            elif is_converted_dir(d):
                stats.skipped_converted_dirs_count += 1
            else:
                filtered_dirs.append(d)
        dirs[:] = filtered_dirs

        for file_name in files:
            stats.total_files_scanned += 1

            # 1. Dateien ausschließen, die mit einem Punkt (.) beginnen (z. B. .DS_Store, ._*)
            if is_dot_file_or_dir(file_name):
                stats.skipped_dot_files_count += 1
                continue

            # 2. Prüfen, ob es eine Bilddatei ist (falls nur Bilder gewünscht)
            if only_images and not is_image_file(file_name, extensions):
                stats.skipped_non_image_files_count += 1
                continue

            # Zielpfad mit gleicher Verzeichnisstruktur bestimmen
            src_file = current_dir / file_name
            rel_path = src_file.relative_to(src_path)
            dst_file = dst_path / rel_path

            if not dry_run:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                if not overwrite and dst_file.exists() and dst_file.stat().st_size == src_file.stat().st_size:
                    stats.skipped_existing_count += 1
                else:
                    shutil.copy2(src_file, dst_file)
                    stats.copied_count += 1
            else:
                stats.copied_count += 1

            processed = stats.copied_count + stats.skipped_existing_count
            if verbose and (processed % 250 == 0 or processed == 1):
                action = "Gefunden" if dry_run else "Verarbeitet"
                print(f"[{action}] {processed} passende Bilder erfasst...")

    if verbose:
        print("\n" + "=" * 60)
        print("Zusammenfassung des Kopiervorgangs:")
        print(f"  - Neu kopierte Bilder:                     {stats.copied_count}")
        print(f"  - Bereits vorhandene (übersprungen):      {stats.skipped_existing_count}")
        print(f"  - Gesamt passende Bilder:                 {stats.copied_count + stats.skipped_existing_count}")
        print(f"  - Übersprungene Punkt-Dateien (.DS_Store): {stats.skipped_dot_files_count}")
        print(f"  - Übersprungene 'Converted'-Verzeichnisse: {stats.skipped_converted_dirs_count}")
        print(f"  - Übersprungene Punkt-Ordner:             {stats.skipped_dot_dirs_count}")
        print(f"  - Übersprungene Nicht-Bild-Dateien:       {stats.skipped_non_image_files_count}")
        print(f"  - Gesamt gescannte Dateien (in Quelle):   {stats.total_files_scanned}")
        print("=" * 60)

    return stats


def main():
    # Sicherstellen, dass Ausgaben mit UTF-8 auf der Konsole korrekt angezeigt werden
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(
        description="Kopiert Bilddateien unter Beibehaltung der Verzeichnisstruktur mit Filterung."
    )
    parser.add_argument(
        "--source",
        type=str,
        default=DEFAULT_SOURCE_DIR,
        help=f"Quellverzeichnis (Standard: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=DEFAULT_TARGET_DIR,
        help=f"Zielverzeichnis (Standard: {DEFAULT_TARGET_DIR})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Überschreibt bereits im Ziel vorhandene Dateien gleicher Größe.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simuliert den Kopiervorgang, ohne Dateien auf die Festplatte zu schreiben.",
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Kopiert alle Dateien (nicht nur bekannte Bildformate), sofern sie den Filtern entsprechen.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Unterdrückt detaillierte Fortschrittsausgaben.",
    )
    parser.add_argument(
        "--generate-doc",
        action="store_true",
        help="Erstellt nach dem Kopieren direkt die interaktive HTML-Dokumentation.",
    )
    parser.add_argument(
        "--doc-target",
        type=str,
        default=r"D:\CleanedImagesHTML",
        help="Zielverzeichnis für die HTML-Dokumentation (Standard: D:\\CleanedImagesHTML).",
    )

    args = parser.parse_args()

    copy_cleaned_images(
        source_dir=args.source,
        target_dir=args.target,
        only_images=not args.all_files,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        verbose=not args.quiet,
    )

    if args.generate_doc and not args.dry_run:
        from generate_doc import generate_html_documentation
        generate_html_documentation(
            source_dir=args.target,
            target_dir=args.doc_target,
            verbose=not args.quiet,
        )


if __name__ == "__main__":
    main()
