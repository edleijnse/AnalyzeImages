"""
Modul zur Erstellung einer interaktiven HTML-Dokumentation für Bildsammlungen.
Liest Bilder und Metadaten (EXIF, IPTC, Dateisystem) aus, erzeugt optimierte Vorschau-Thumbnails
und generiert eine moderne, offlinefähige Web-Applikation mit Galerie, Verzeichnisbaum und
strukturiertem Metadaten-Inspektor.
"""

import argparse
import concurrent.futures
import datetime
import html
import json
import os
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import ExifTags, Image, ImageOps

DEFAULT_SOURCE_DIR = r"D:\CleanedImages"
DEFAULT_TARGET_DIR = r"D:\CleanedImagesHTML"
DEFAULT_THUMBNAIL_SIZE = 480
DEFAULT_THUMBNAIL_QUALITY = 82

IMAGE_EXTENSIONS: Set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
}

# EXIF Human-Readable Mappings
EXPOSURE_PROGRAM_MAP = {
    0: "Nicht definiert",
    1: "Manuell",
    2: "Normalprogramm (P)",
    3: "Zeitautomatik (A / Av - Blendenvorwahl)",
    4: "Blendenautomatik (S / Tv - Zeitvorwahl)",
    5: "Kreativprogramm (Schärfentiefe)",
    6: "Aktionsprogramm (schnelle Verschlusszeit)",
    7: "Porträtmodus",
    8: "Landschaftsmodus",
}

METERING_MODE_MAP = {
    0: "Unbekannt",
    1: "Durchschnittsmessung",
    2: "Mittenbetonte Integralmessung",
    3: "Spotmessung",
    4: "Mehrfach-Spotmessung",
    5: "Mehrfeldmessung / Matrix",
    6: "Teilmessung",
    255: "Andere",
}

FLASH_MAP = {
    0x0000: "Blitz nicht ausgelöst",
    0x0001: "Blitz ausgelöst",
    0x0005: "Blitz ausgelöst, kein Messblitz-Rückwurf",
    0x0007: "Blitz ausgelöst, Messblitz-Rückwurf erkannt",
    0x0009: "Blitz ausgelöst, Zwangsblitz",
    0x000D: "Blitz ausgelöst, Zwangsblitz, kein Rückwurf",
    0x000F: "Blitz ausgelöst, Zwangsblitz, Rückwurf erkannt",
    0x0010: "Blitz nicht ausgelöst, Zwangsmodus",
    0x0018: "Blitz nicht ausgelöst, Automatikmodus",
    0x0019: "Blitz ausgelöst, Automatikmodus",
    0x001D: "Blitz ausgelöst, Automatikmodus, kein Rückwurf",
    0x001F: "Blitz ausgelöst, Automatikmodus, Rückwurf erkannt",
    0x0020: "Keine Blitzfunktion vorhanden",
    0x0041: "Blitz ausgelöst, Rote-Augen-Reduktion",
    0x0045: "Blitz ausgelöst, Rote-Augen-Reduktion, kein Rückwurf",
    0x0047: "Blitz ausgelöst, Rote-Augen-Reduktion, Rückwurf erkannt",
    0x0049: "Blitz ausgelöst, Zwangsmodus, Rote-Augen-Reduktion",
}

WHITE_BALANCE_MAP = {
    0: "Automatisch (Auto)",
    1: "Manuell",
}

COLOR_SPACE_MAP = {
    1: "sRGB",
    65535: "Unkalibriert (z. B. Adobe RGB)",
}


def format_bytes(size: int) -> str:
    """Formatiert Dateigrößen benutzerfreundlich."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


def format_exposure_time(val: Any) -> Optional[str]:
    """Formatiert die Belichtungszeit übersichtlich (z. B. 1/125s oder 2.5s)."""
    if val is None:
        return None
    try:
        f_val = float(val)
        if f_val <= 0:
            return None
        if f_val >= 1.0:
            return f"{f_val:.1f}s" if f_val % 1 != 0 else f"{int(f_val)}s"
        else:
            # Als Bruch 1/x darstellen
            denom = round(1.0 / f_val)
            return f"1/{denom}s"
    except (ValueError, TypeError, ZeroDivisionError):
        return str(val)


def format_f_number(val: Any) -> Optional[str]:
    """Formatiert den Blendenwert (z. B. f/5.6)."""
    if val is None:
        return None
    try:
        f_val = float(val)
        return f"f/{f_val:.1f}" if f_val % 1 != 0 else f"f/{int(f_val)}"
    except (ValueError, TypeError):
        return str(val)


def format_focal_length(val: Any, val_35mm: Any = None) -> Optional[str]:
    """Formatiert die Brennweite (z. B. 50 mm oder 50 mm (KB: 75 mm))."""
    if val is None:
        return None
    try:
        f_val = float(val)
        base = f"{f_val:.1f} mm" if f_val % 1 != 0 else f"{int(f_val)} mm"
        if val_35mm:
            try:
                f_35 = float(val_35mm)
                base += f" (KB: {int(f_35)} mm)"
            except (ValueError, TypeError):
                pass
        return base
    except (ValueError, TypeError):
        return str(val)


def safe_serialize(obj: Any) -> Any:
    """Wandelt EXIF-Objekte (IFDRational, bytes etc.) in serialisierbare Typen um."""
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8", errors="replace").strip("\x00")
        except Exception:
            return str(obj)
    elif hasattr(obj, "numerator") and hasattr(obj, "denominator"):
        try:
            if obj.denominator == 1:
                return obj.numerator
            return float(obj)
        except ZeroDivisionError:
            return 0
    elif isinstance(obj, (int, float, str, bool)):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [safe_serialize(x) for x in obj]
    elif isinstance(obj, dict):
        return {str(k): safe_serialize(v) for k, v in obj.items()}
    return str(obj)


def url_encode_path(rel_path_str: str) -> str:
    """Enkodiert Pfade sicher für URLs (inkl. Sonderzeichen und Leerzeichen)."""
    parts = Path(rel_path_str).parts
    return "/".join(urllib.parse.quote(part) for part in parts)


@dataclass
class ImageMetadata:
    id: int
    filename: str
    relative_path: str
    directory: str
    extension: str
    file_size_bytes: int
    file_size_formatted: str
    modified_date: str
    
    # Dimensionen
    width: int
    height: int
    megapixels: float
    aspect_ratio: str
    format: str
    color_mode: str
    dpi_x: Optional[float] = None
    dpi_y: Optional[float] = None

    # Kamera & Aufnahme
    make: Optional[str] = None
    model: Optional[str] = None
    lens: Optional[str] = None
    date_original: Optional[str] = None
    date_time: Optional[str] = None
    exposure_time: Optional[str] = None
    f_number: Optional[str] = None
    iso: Optional[int] = None
    focal_length: Optional[str] = None
    exposure_program: Optional[str] = None
    metering_mode: Optional[str] = None
    flash: Optional[str] = None
    white_balance: Optional[str] = None
    color_space: Optional[str] = None
    orientation: Optional[int] = None

    # Urheber & Software
    software: Optional[str] = None
    artist: Optional[str] = None
    copyright: Optional[str] = None
    description: Optional[str] = None

    # URLs
    url_original: str = ""
    url_thumbnail: str = ""

    # Vollständige EXIF-Rohdaten
    raw_exif: Dict[str, Any] = field(default_factory=dict)


def extract_metadata_from_file(file_path: Path, base_path: Path, image_id: int) -> Optional[ImageMetadata]:
    """Extrahiert alle Metadaten aus einer Bilddatei."""
    try:
        rel_path = file_path.relative_to(base_path)
        rel_dir = str(rel_path.parent) if str(rel_path.parent) != "." else ""
        stat = file_path.stat()
        
        file_size = stat.st_size
        mod_date = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

        with Image.open(file_path) as img:
            width, height = img.size
            img_format = img.format or file_path.suffix.lstrip(".").upper()
            mode = img.mode

            # DPI
            dpi_x, dpi_y = None, None
            dpi_info = img.info.get("dpi")
            if dpi_info and isinstance(dpi_info, (tuple, list)) and len(dpi_info) >= 2:
                try:
                    dpi_x, dpi_y = round(float(dpi_info[0]), 1), round(float(dpi_info[1]), 1)
                except (ValueError, TypeError):
                    pass

            # EXIF
            raw_exif_dict: Dict[str, Any] = {}
            make, model, software, artist, copyright_val, desc = None, None, None, None, None, None
            date_orig, date_time = None, None
            exp_time, f_num, iso_val, focal_len, focal_35 = None, None, None, None, None
            exp_prog, met_mode, flash_val, wb_val, cs_val, orient_val = None, None, None, None, None, None
            lens_spec = None

            try:
                exif_data = img.getexif()
                if exif_data:
                    # Haupt-EXIF-Tags
                    for tag_id, value in exif_data.items():
                        tag_name = ExifTags.TAGS.get(tag_id, f"Tag_{tag_id}")
                        raw_exif_dict[tag_name] = safe_serialize(value)
                        
                        if tag_id == 271:  # Make
                            make = str(value).strip()
                        elif tag_id == 272:  # Model
                            model = str(value).strip()
                        elif tag_id == 305:  # Software
                            software = str(value).strip()
                        elif tag_id == 315:  # Artist
                            artist = str(value).strip()
                        elif tag_id == 33432:  # Copyright
                            copyright_val = str(value).strip()
                        elif tag_id == 270:  # ImageDescription
                            desc = str(value).strip()
                        elif tag_id == 306:  # DateTime
                            date_time = str(value).strip()
                        elif tag_id == 274:  # Orientation
                            orient_val = int(value) if isinstance(value, (int, float)) else None
                        elif tag_id == 282 and dpi_x is None:  # XResolution
                            try:
                                dpi_x = round(float(value), 1)
                            except Exception:
                                pass
                        elif tag_id == 283 and dpi_y is None:  # YResolution
                            try:
                                dpi_y = round(float(value), 1)
                            except Exception:
                                pass

                    # IFD Sub-Tags (ExifIFD)
                    try:
                        exif_ifd = exif_data.get_ifd(ExifTags.IFD.Exif)
                        if exif_ifd:
                            for tag_id, value in exif_ifd.items():
                                tag_name = ExifTags.TAGS.get(tag_id, f"ExifIFD_{tag_id}")
                                raw_exif_dict[tag_name] = safe_serialize(value)

                                if tag_id == 36867:  # DateTimeOriginal
                                    date_orig = str(value).strip()
                                elif tag_id == 33434:  # ExposureTime
                                    exp_time = value
                                elif tag_id == 33437:  # FNumber
                                    f_num = value
                                elif tag_id == 34855:  # ISOSpeedRatings
                                    try:
                                        iso_val = int(value)
                                    except Exception:
                                        pass
                                elif tag_id == 37386:  # FocalLength
                                    focal_len = value
                                elif tag_id == 41989:  # FocalLengthIn35mmFilm
                                    focal_35 = value
                                elif tag_id == 34850:  # ExposureProgram
                                    exp_prog = EXPOSURE_PROGRAM_MAP.get(int(value), str(value))
                                elif tag_id == 37383:  # MeteringMode
                                    met_mode = METERING_MODE_MAP.get(int(value), str(value))
                                elif tag_id == 37385:  # Flash
                                    flash_val = FLASH_MAP.get(int(value), f"Code {value}")
                                elif tag_id == 41987:  # WhiteBalance
                                    wb_val = WHITE_BALANCE_MAP.get(int(value), str(value))
                                elif tag_id == 40961:  # ColorSpace
                                    cs_val = COLOR_SPACE_MAP.get(int(value), str(value))
                                elif tag_id == 42036:  # LensModel / LensSpecification
                                    lens_spec = str(value).strip()
                    except Exception:
                        pass
            except Exception:
                pass

        # Berechnete Werte
        mp = round((width * height) / 1_000_000.0, 1)
        # Seitenverhältnis vereinfachen
        gcd_val = _calc_aspect_ratio(width, height)

        url_orig = "../CleanedImages/" + url_encode_path(str(rel_path))
        thumb_rel_path = Path(rel_dir) / f"{file_path.stem}.jpg"
        url_thumb = "thumbnails/" + url_encode_path(str(thumb_rel_path))

        return ImageMetadata(
            id=image_id,
            filename=file_path.name,
            relative_path=str(rel_path).replace("\\", "/"),
            directory=rel_dir.replace("\\", "/"),
            extension=file_path.suffix.lower(),
            file_size_bytes=file_size,
            file_size_formatted=format_bytes(file_size),
            modified_date=mod_date,
            width=width,
            height=height,
            megapixels=mp,
            aspect_ratio=gcd_val,
            format=img_format,
            color_mode=mode,
            dpi_x=dpi_x,
            dpi_y=dpi_y,
            make=make,
            model=model,
            lens=lens_spec,
            date_original=date_orig or date_time,
            date_time=date_time,
            exposure_time=format_exposure_time(exp_time),
            f_number=format_f_number(f_num),
            iso=iso_val,
            focal_length=format_focal_length(focal_len, focal_35),
            exposure_program=exp_prog,
            metering_mode=met_mode,
            flash=flash_val,
            white_balance=wb_val,
            color_space=cs_val,
            orientation=orient_val,
            software=software,
            artist=artist,
            copyright=copyright_val,
            description=desc,
            url_original=url_orig,
            url_thumbnail=url_thumb,
            raw_exif=raw_exif_dict,
        )
    except Exception as e:
        print(f"Warnung: Metadaten für {file_path} konnten nicht gelesen werden: {e}", file=sys.stderr)
        return None


def _calc_aspect_ratio(w: int, h: int) -> str:
    """Berechnet das Seitenverhältnis als Bruch oder Dezimalangabe."""
    if w <= 0 or h <= 0:
        return "-"
    # Gängige fotografische Verhältnisse prüfen
    ratio = w / h
    tolerances = [
        (3 / 2, "3:2"),
        (2 / 3, "2:3"),
        (4 / 3, "4:3"),
        (3 / 4, "3:4"),
        (16 / 9, "16:9"),
        (9 / 16, "9:16"),
        (1 / 1, "1:1"),
        (1.414, "DIN (1:√2)"),
    ]
    for target, label in tolerances:
        if abs(ratio - target) < 0.03:
            return label
    return f"{ratio:.2f}:1"


def create_thumbnail_worker(args: Tuple[str, str, int, int]) -> bool:
    """Worker-Funktion für parallele Thumbnail-Generierung."""
    src_file_str, dst_file_str, max_size, quality = args
    src_path = Path(src_file_str)
    dst_path = Path(dst_file_str)

    try:
        # Falls Thumbnail existiert und neuer als Quelle ist, überspringen
        if dst_path.exists() and dst_path.stat().st_size > 0:
            if dst_path.stat().st_mtime >= src_path.stat().st_mtime:
                return True

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(src_path) as img:
            # EXIF Orientierung automatisch korrigieren
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Farbraum RGB für JPEG sicherstellen
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1] if len(img.split()) == 4 else None)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            img.save(dst_path, "JPEG", quality=quality, optimize=True)
            return True
    except Exception as e:
        print(f"Fehler bei Thumbnail-Erstellung für {src_path}: {e}", file=sys.stderr)
        return False


def build_directory_tree(directories: List[str], dir_counts: Dict[str, int]) -> Dict[str, Any]:
    """Erstellt eine verschachtelte Baumstruktur aus Verzeichnispfaden für die Navigation."""
    root: Dict[str, Any] = {
        "name": "Hauptverzeichnis",
        "path": "",
        "count": sum(dir_counts.values()),
        "direct_count": dir_counts.get("", 0),
        "children": {},
    }

    for d in sorted(directories):
        if not d:
            continue
        parts = Path(d).parts
        current = root
        curr_path = ""
        for i, part in enumerate(parts):
            curr_path = f"{curr_path}/{part}" if curr_path else part
            if part not in current["children"]:
                current["children"][part] = {
                    "name": part,
                    "path": curr_path,
                    "count": 0,
                    "direct_count": 0,
                    "children": {},
                }
            current = current["children"][part]

    # Zählungen aggregieren
    def aggregate_counts(node: Dict[str, Any]) -> int:
        node_path = node["path"]
        total = dir_counts.get(node_path, 0)
        node["direct_count"] = total
        for child in node["children"].values():
            total += aggregate_counts(child)
        node["count"] = total
        return total

    aggregate_counts(root)

    # In Arrays konvertieren für saubere JSON-Struktur
    def to_tree_list(node: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": node["name"],
            "path": node["path"],
            "count": node["count"],
            "direct_count": node["direct_count"],
            "children": [to_tree_list(c) for c in sorted(node["children"].values(), key=lambda x: x["name"])],
        }

    return to_tree_list(root)


def generate_html_documentation(
    source_dir: Path | str = DEFAULT_SOURCE_DIR,
    target_dir: Path | str = DEFAULT_TARGET_DIR,
    thumbnail_size: int = DEFAULT_THUMBNAIL_SIZE,
    thumbnail_quality: int = DEFAULT_THUMBNAIL_QUALITY,
    skip_thumbnails: bool = False,
    workers: Optional[int] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Generiert die vollständige HTML-Dokumentation in target_dir."""
    src_path = Path(source_dir).resolve()
    dst_path = Path(target_dir).resolve()

    if not src_path.exists():
        raise FileNotFoundError(f"Quellverzeichnis existiert nicht: {src_path}")

    dst_path.mkdir(parents=True, exist_ok=True)
    thumbnails_dir = dst_path / "thumbnails"

    if verbose:
        print("=" * 65)
        print("Starte Erstellung der HTML-Bilder-Dokumentation")
        print(f"Quelle:    {src_path}")
        print(f"Ziel:      {dst_path}")
        print(f"Thumbnails: {'Deaktiviert' if skip_thumbnails else f'Aktiv ({thumbnail_size}px, Q{thumbnail_quality})'}")
        print("=" * 65)

    start_time = time.time()

    # 1. Bilddateien sammeln
    image_files: List[Path] = []
    for root, _, files in os.walk(src_path):
        for f in files:
            if Path(f).suffix.lower() in IMAGE_EXTENSIONS and not f.startswith("."):
                image_files.append(Path(root) / f)

    image_files.sort(key=lambda p: str(p.relative_to(src_path)).lower())
    if verbose:
        print(f"-> {len(image_files)} passende Bilder gefunden. Lese Metadaten aus...")

    # 2. Metadaten extrahieren
    metadata_list: List[ImageMetadata] = []
    dir_counts: Dict[str, int] = {}
    directories_set: Set[str] = set()
    cameras_dict: Dict[str, int] = {}
    years_dict: Dict[str, int] = {}
    total_bytes = 0

    for idx, img_path in enumerate(image_files, start=1):
        meta = extract_metadata_from_file(img_path, src_path, idx)
        if meta:
            metadata_list.append(meta)
            total_bytes += meta.file_size_bytes
            
            d_norm = meta.directory
            directories_set.add(d_norm)
            dir_counts[d_norm] = dir_counts.get(d_norm, 0) + 1

            cam = f"{meta.make} {meta.model}".strip() if (meta.make or meta.model) else "Ohne EXIF-Kamera"
            cameras_dict[cam] = cameras_dict.get(cam, 0) + 1

            year = "Unbekannt"
            if meta.date_original:
                try:
                    year = meta.date_original[:4]
                    if not (year.isdigit() and len(year) == 4):
                        year = "Unbekannt"
                except Exception:
                    year = "Unbekannt"
            years_dict[year] = years_dict.get(year, 0) + 1

        if verbose and (idx % 300 == 0 or idx == len(image_files)):
            print(f"   [{idx}/{len(image_files)}] Metadaten erfasst...")

    # 3. Thumbnails generieren (Multiprocessing)
    if not skip_thumbnails:
        if verbose:
            print(f"\n-> Generiere Thumbnails ({len(metadata_list)} Bilder)...")
        tasks = []
        for meta in metadata_list:
            src_f = src_path / Path(meta.relative_path)
            thumb_rel = Path(meta.directory) / f"{src_f.stem}.jpg" if meta.directory else f"{src_f.stem}.jpg"
            dst_f = thumbnails_dir / thumb_rel
            tasks.append((str(src_f), str(dst_f), thumbnail_size, thumbnail_quality))

        worker_count = workers if workers is not None else min(12, os.cpu_count() or 4)
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(create_thumbnail_worker, tasks))
        created_count = sum(1 for r in results if r)
        if verbose:
            print(f"   Thumbnails erfolgreich generiert/überprüft: {created_count}/{len(tasks)}")

    # 4. Datenstruktur aufbauen
    tree_data = build_directory_tree(list(directories_set), dir_counts)

    cameras_sorted = [{"name": k, "count": v} for k, v in sorted(cameras_dict.items(), key=lambda x: -x[1])]
    years_sorted = [{"year": k, "count": v} for k, v in sorted(years_dict.items(), key=lambda x: x[0])]

    doc_data = {
        "title": "Bilder-Dokumentation & Metadaten-Archiv",
        "source_directory": str(src_path),
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_images": len(metadata_list),
        "total_size_bytes": total_bytes,
        "total_size_formatted": format_bytes(total_bytes),
        "total_directories": len(dir_counts),
        "directory_tree": tree_data,
        "directories_list": sorted(list(directories_set)),
        "cameras": cameras_sorted,
        "years": years_sorted,
        "images": [asdict(m) for m in metadata_list],
    }

    # 5. data.js schreiben (als globales JS-Objekt, um CORS im Browser-Dateimodus zu verhindern)
    data_js_path = dst_path / "data.js"
    with open(data_js_path, "w", encoding="utf-8") as f:
        f.write("/* Automatisch generierte Metadaten-Datenbank */\n")
        f.write("window.DOCUMENTATION_DATA = ")
        json.dump(doc_data, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    # 6. HTML, CSS, JS schreiben
    write_web_assets(dst_path)

    elapsed = round(time.time() - start_time, 2)
    if verbose:
        print("\n" + "=" * 65)
        print("Dokumentation erfolgreich erstellt!")
        print(f"  - Gesamtzahl Bilder:       {len(metadata_list)}")
        print(f"  - Gesamtvolumen:           {format_bytes(total_bytes)}")
        print(f"  - Verzeichnisse:           {len(dir_counts)}")
        print(f"  - HTML-Index:              {dst_path / 'index.html'}")
        print(f"  - Daten-Datei:             {data_js_path}")
        print(f"  - Benötigte Zeit:          {elapsed} Sekunden")
        print("=" * 65)

    return doc_data


def write_web_assets(dst_path: Path) -> None:
    """Schreibt index.html, styles.css und app.js in das Zielverzeichnis."""
    index_html = dst_path / "index.html"
    styles_css = dst_path / "styles.css"
    app_js = dst_path / "app.js"

    styles_css.write_text(CSS_CONTENT, encoding="utf-8")
    app_js.write_text(JS_CONTENT, encoding="utf-8")
    index_html.write_text(HTML_CONTENT, encoding="utf-8")


# ==============================================================================
# HTML, CSS und JS Templates
# ==============================================================================

HTML_CONTENT = """<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bilder-Dokumentation &amp; Metadaten-Archiv</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body class="theme-dark">
    <!-- Header / Navbar -->
    <header class="app-header">
        <div class="header-left">
            <button id="toggle-sidebar-btn" class="icon-btn" title="Verzeichnisbaum ein-/ausblenden">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
            </button>
            <div class="branding">
                <h1>Bilder-Dokumentation</h1>
                <span class="source-tag" id="stat-source" title="Quellverzeichnis">D:\\CleanedImages</span>
            </div>
        </div>

        <div class="header-center">
            <div class="search-box">
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
                <input type="text" id="search-input" placeholder="Suchen nach Dateiname, Ordner, Kamera, Jahr, Metadaten..." autocomplete="off">
                <button id="search-clear-btn" class="clear-btn" title="Suche leeren" style="display:none;">&times;</button>
            </div>
        </div>

        <div class="header-right">
            <div class="header-stats">
                <div class="stat-badge" title="Gesamtzahl Bilder"><span class="stat-val" id="stat-count">0</span> Bilder</div>
                <div class="stat-badge" title="Gesamtes Speichervolumen"><span class="stat-val" id="stat-size">0 MB</span></div>
            </div>

            <div class="view-toggles">
                <button id="view-grid-btn" class="toggle-btn active" title="Galerie-Kacheln">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                </button>
                <button id="view-table-btn" class="toggle-btn" title="Tabellarische Metadatenliste">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
                </button>
            </div>

            <button id="theme-toggle-btn" class="icon-btn" title="Design umschalten (Hell/Dunkel)">
                <svg id="theme-icon-sun" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            </button>
        </div>
    </header>

    <div class="app-layout">
        <!-- Sidebar mit Verzeichnisbaum & Filter -->
        <aside class="sidebar" id="sidebar">
            <div class="sidebar-header">
                <h3>Verzeichnisse</h3>
                <button id="reset-folder-btn" class="text-btn" title="Alle Ordner auswählen">Alle anzeigen</button>
            </div>
            
            <div class="tree-container" id="tree-container">
                <!-- Verzeichnisbaum wird per JavaScript gerendert -->
            </div>

            <div class="sidebar-section">
                <h3>Filter &amp; Kriterien</h3>
                <div class="filter-group">
                    <label for="filter-camera">Kamera:</label>
                    <select id="filter-camera">
                        <option value="">Alle Kameras</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label for="filter-year">Jahr:</label>
                    <select id="filter-year">
                        <option value="">Alle Jahre</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label for="sort-select">Sortierung:</label>
                    <select id="sort-select">
                        <option value="name-asc">Dateiname (A &rarr; Z)</option>
                        <option value="name-desc">Dateiname (Z &rarr; A)</option>
                        <option value="date-desc">Aufnahmedatum (Neueste zuerst)</option>
                        <option value="date-asc">Aufnahmedatum (Älteste zuerst)</option>
                        <option value="size-desc">Dateigröße (Größte zuerst)</option>
                        <option value="mp-desc">Auflösung (Höchste MP zuerst)</option>
                    </select>
                </div>
                <button id="reset-all-filters-btn" class="action-btn secondary full-width">Alle Filter zurücksetzen</button>
            </div>
        </aside>

        <!-- Hauptbereich -->
        <main class="main-content">
            <!-- Pfad- & Kontrollleiste -->
            <div class="control-bar">
                <nav class="breadcrumbs" id="breadcrumbs">
                    <span class="crumb active" data-path="">Alle Verzeichnisse</span>
                </nav>
                <div class="control-actions">
                    <span class="results-count" id="results-count">Lade Daten...</span>
                    
                    <div class="grid-size-controls" id="grid-size-controls">
                        <span class="label">Größe:</span>
                        <button class="size-btn" data-size="small" title="Kompakt">S</button>
                        <button class="size-btn active" data-size="medium" title="Mittel">M</button>
                        <button class="size-btn" data-size="large" title="Groß">L</button>
                    </div>
                </div>
            </div>

            <!-- Galerieansicht (Kacheln) -->
            <div class="gallery-container grid-medium" id="gallery-container">
                <!-- Dynamisch generierte Bildkarten -->
            </div>

            <!-- Tabellenansicht (Listenansicht mit Metadaten) -->
            <div class="table-container" id="table-container" style="display: none;">
                <table class="metadata-table">
                    <thead>
                        <tr>
                            <th style="width: 60px;">Vorschau</th>
                            <th data-sort="name">Dateiname</th>
                            <th data-sort="folder">Verzeichnis</th>
                            <th data-sort="dimensions">Abmessungen</th>
                            <th data-sort="size">Größe</th>
                            <th data-sort="camera">Kamera</th>
                            <th data-sort="date">Aufnahmedatum</th>
                            <th>Belichtung</th>
                            <th style="width: 70px;">Aktion</th>
                        </tr>
                    </thead>
                    <tbody id="table-body">
                        <!-- Dynamisch generierte Tabellenzeilen -->
                    </tbody>
                </table>
            </div>

            <!-- Pagination / Mehr laden -->
            <div class="pagination-bar" id="pagination-bar">
                <div class="page-info" id="page-info">Zeige Seite 1</div>
                <div class="page-controls" id="page-controls">
                    <!-- Pagination-Buttons -->
                </div>
                <div class="page-size-selector">
                    <label for="page-size-select">Einträge pro Seite:</label>
                    <select id="page-size-select">
                        <option value="48">48</option>
                        <option value="96" selected>96</option>
                        <option value="200">200</option>
                        <option value="999999">Alle</option>
                    </select>
                </div>
            </div>
        </main>
    </div>

    <!-- Detail-Modal / Lightbox mit Metadaten-Inspektor -->
    <div class="modal" id="detail-modal" style="display: none;">
        <div class="modal-backdrop" id="modal-backdrop"></div>
        <div class="modal-content">
            <!-- Modal Header -->
            <div class="modal-header">
                <div class="modal-title-area">
                    <h2 id="modal-filename">Dateiname.jpg</h2>
                    <span class="modal-path" id="modal-path">Verzeichnis/Pfad</span>
                </div>
                <div class="modal-header-actions">
                    <button id="modal-open-original" class="action-btn secondary" title="Originalbild in neuem Tab öffnen">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                        Original anzeigen
                    </button>
                    <button id="modal-close-btn" class="icon-btn close-btn" title="Schließen (Esc)">&times;</button>
                </div>
            </div>

            <!-- Modal Body (Split: Bild + Metadaten) -->
            <div class="modal-body">
                <!-- Linke Seite: Bild-Viewer -->
                <div class="modal-image-wrapper">
                    <button class="nav-btn prev-btn" id="modal-prev-btn" title="Vorheriges Bild (Pfeil links)">&#10094;</button>
                    <div class="image-stage" id="image-stage">
                        <img id="modal-img" src="" alt="Vorschau">
                    </div>
                    <button class="nav-btn next-btn" id="modal-next-btn" title="Nächstes Bild (Pfeil rechts)">&#10095;</button>
                    
                    <div class="viewer-toolbar">
                        <button id="zoom-in-btn" class="tool-btn" title="Vergrößern">+</button>
                        <button id="zoom-out-btn" class="tool-btn" title="Verkleinern">-</button>
                        <button id="zoom-reset-btn" class="tool-btn" title="Zurücksetzen">100%</button>
                        <button id="fullscreen-btn" class="tool-btn" title="Vollbild">Vollbild</button>
                    </div>
                </div>

                <!-- Rechte Seite: Metadaten-Inspektor -->
                <div class="modal-metadata-panel">
                    <div class="panel-tabs">
                        <button class="tab-btn active" data-tab="tab-overview">Übersicht</button>
                        <button class="tab-btn" data-tab="tab-photo">Aufnahme &amp; EXIF</button>
                        <button class="tab-btn" data-tab="tab-system">Datei &amp; System</button>
                        <button class="tab-btn" data-tab="tab-raw">Rohdaten</button>
                    </div>

                    <!-- Tab 1: Übersicht -->
                    <div class="tab-content active" id="tab-overview">
                        <div class="meta-section">
                            <h4>Bilddaten &amp; Dimensionen</h4>
                            <div class="meta-grid" id="meta-grid-overview">
                                <!-- Dynamisch befüllt -->
                            </div>
                        </div>
                        <div class="meta-section">
                            <h4>Kamera-Schnellübersicht</h4>
                            <div class="meta-grid" id="meta-grid-cam-summary">
                                <!-- Dynamisch befüllt -->
                            </div>
                        </div>
                    </div>

                    <!-- Tab 2: Aufnahme & EXIF -->
                    <div class="tab-content" id="tab-photo">
                        <div class="meta-section">
                            <h4>Fotografische Einstellungen</h4>
                            <div class="meta-grid" id="meta-grid-photo">
                                <!-- Dynamisch befüllt -->
                            </div>
                        </div>
                        <div class="meta-section" id="meta-section-author">
                            <h4>Autor, Software &amp; Urheberrecht</h4>
                            <div class="meta-grid" id="meta-grid-author">
                                <!-- Dynamisch befüllt -->
                            </div>
                        </div>
                    </div>

                    <!-- Tab 3: Datei & System -->
                    <div class="tab-content" id="tab-system">
                        <div class="meta-section">
                            <h4>Dateisystem &amp; Format</h4>
                            <div class="meta-grid" id="meta-grid-system">
                                <!-- Dynamisch befüllt -->
                            </div>
                        </div>
                        <div class="panel-actions">
                            <button id="copy-path-btn" class="action-btn secondary full-width">Dateipfad kopieren</button>
                            <button id="copy-json-btn" class="action-btn secondary full-width">Metadaten als JSON kopieren</button>
                        </div>
                    </div>

                    <!-- Tab 4: Alle Rohdaten -->
                    <div class="tab-content" id="tab-raw">
                        <div class="raw-search">
                            <input type="text" id="raw-filter-input" placeholder="Tag-Namen oder Werte filtern...">
                        </div>
                        <div class="raw-table-wrapper">
                            <table class="raw-exif-table">
                                <thead>
                                    <tr>
                                        <th>EXIF Tag</th>
                                        <th>Wert</th>
                                    </tr>
                                </thead>
                                <tbody id="raw-exif-tbody">
                                    <!-- Rohdaten-Zeilen -->
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Notification Toast -->
    <div id="toast" class="toast" style="display:none;"></div>

    <!-- Datenquelle einbinden -->
    <script src="data.js"></script>
    <script src="app.js"></script>
</body>
</html>
"""

CSS_CONTENT = """/* CSS-Design für Bilder-Dokumentation */
:root {
    --bg-primary: #12151c;
    --bg-secondary: #1a1e28;
    --bg-surface: #222736;
    --bg-hover: #2c3345;
    --border-color: #31384d;
    --text-primary: #f0f3f8;
    --text-secondary: #9aa5b8;
    --text-muted: #647087;
    --accent: #3b82f6;
    --accent-hover: #60a5fa;
    --accent-subtle: rgba(59, 130, 246, 0.15);
    --success: #10b981;
    --card-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
    --radius: 8px;
    --header-height: 64px;
    --sidebar-width: 320px;
}

body.theme-light {
    --bg-primary: #f8fafc;
    --bg-secondary: #f1f5f9;
    --bg-surface: #ffffff;
    --bg-hover: #e2e8f0;
    --border-color: #cbd5e1;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-muted: #94a3b8;
    --accent: #2563eb;
    --accent-hover: #1d4ed8;
    --accent-subtle: rgba(37, 99, 235, 0.1);
    --card-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background-color: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
    overflow-x: hidden;
}

/* Header */
.app-header {
    height: var(--header-height);
    background-color: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 1.25rem;
    position: sticky;
    top: 0;
    z-index: 100;
}

.header-left {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.branding h1 {
    font-size: 1.15rem;
    font-weight: 700;
    line-height: 1.2;
}

.source-tag {
    font-size: 0.75rem;
    color: var(--text-muted);
    font-family: monospace;
}

.header-center {
    flex: 1;
    max-width: 520px;
    margin: 0 1rem;
}

.search-box {
    display: flex;
    align-items: center;
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 0.35rem 0.75rem;
    gap: 0.5rem;
    transition: border-color 0.2s;
}

.search-box:focus-within {
    border-color: var(--accent);
}

.search-box input {
    background: transparent;
    border: none;
    color: var(--text-primary);
    font-size: 0.9rem;
    width: 100%;
    outline: none;
}

.clear-btn {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1.2rem;
    cursor: pointer;
}

.header-right {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.header-stats {
    display: flex;
    gap: 0.5rem;
}

.stat-badge {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    padding: 0.25rem 0.6rem;
    font-size: 0.8rem;
    color: var(--text-secondary);
}

.stat-badge .stat-val {
    font-weight: 700;
    color: var(--accent);
}

.view-toggles {
    display: flex;
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    overflow: hidden;
}

.toggle-btn {
    background: transparent;
    border: none;
    padding: 0.4rem 0.6rem;
    color: var(--text-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
}

.toggle-btn.active {
    background-color: var(--accent);
    color: #fff;
}

.icon-btn {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    border-radius: var(--radius);
    padding: 0.45rem;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
}

.icon-btn:hover {
    color: var(--text-primary);
    background-color: var(--bg-hover);
}

/* App Layout */
.app-layout {
    display: flex;
    min-height: calc(100vh - var(--header-height));
}

/* Sidebar */
.sidebar {
    width: var(--sidebar-width);
    background-color: var(--bg-secondary);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    max-height: calc(100vh - var(--header-height));
    position: sticky;
    top: var(--header-height);
    overflow-y: auto;
}

.sidebar.collapsed {
    display: none;
}

.sidebar-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    border-bottom: 1px solid var(--border-color);
}

.sidebar-header h3 {
    font-size: 0.95rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
}

.text-btn {
    background: transparent;
    border: none;
    color: var(--accent);
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
}

.text-btn:hover {
    text-decoration: underline;
}

.tree-container {
    padding: 0.5rem;
    flex: 1;
    overflow-y: auto;
}

.tree-item {
    margin-bottom: 2px;
}

.tree-row {
    display: flex;
    align-items: center;
    padding: 0.35rem 0.5rem;
    border-radius: 4px;
    cursor: pointer;
    gap: 0.35rem;
    font-size: 0.85rem;
    color: var(--text-secondary);
    user-select: none;
    transition: background-color 0.15s;
}

.tree-row:hover {
    background-color: var(--bg-hover);
    color: var(--text-primary);
}

.tree-row.active {
    background-color: var(--accent-subtle);
    color: var(--accent);
    font-weight: 600;
}

.tree-expander {
    width: 14px;
    height: 14px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.65rem;
    color: var(--text-muted);
}

.tree-icon {
    display: inline-flex;
    align-items: center;
}

.tree-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.tree-badge {
    font-size: 0.75rem;
    background-color: var(--bg-surface);
    padding: 1px 6px;
    border-radius: 10px;
    color: var(--text-muted);
}

.tree-children {
    padding-left: 1rem;
    border-left: 1px dashed var(--border-color);
    margin-left: 0.7rem;
}

.sidebar-section {
    padding: 1rem;
    border-top: 1px solid var(--border-color);
}

.sidebar-section h3 {
    font-size: 0.85rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    margin-bottom: 0.75rem;
}

.filter-group {
    margin-bottom: 0.75rem;
}

.filter-group label {
    display: block;
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-bottom: 0.25rem;
}

.filter-group select {
    width: 100%;
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.4rem;
    border-radius: var(--radius);
    font-size: 0.85rem;
    outline: none;
}

.action-btn {
    background-color: var(--accent);
    color: #fff;
    border: none;
    border-radius: var(--radius);
    padding: 0.5rem 1rem;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    transition: background-color 0.2s;
}

.action-btn:hover {
    background-color: var(--accent-hover);
}

.action-btn.secondary {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
}

.action-btn.secondary:hover {
    background-color: var(--bg-hover);
    color: var(--text-primary);
}

.action-btn.full-width {
    width: 100%;
}

/* Main Content */
.main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
}

.control-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1.25rem;
    background-color: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
}

.breadcrumbs {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.35rem;
    font-size: 0.85rem;
}

.crumb {
    color: var(--accent);
    cursor: pointer;
}

.crumb:hover {
    text-decoration: underline;
}

.crumb.active {
    color: var(--text-primary);
    font-weight: 600;
    cursor: default;
}

.crumb.active:hover {
    text-decoration: none;
}

.control-actions {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.results-count {
    font-size: 0.85rem;
    color: var(--text-muted);
}

.grid-size-controls {
    display: flex;
    align-items: center;
    gap: 0.25rem;
}

.grid-size-controls .label {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-right: 0.2rem;
}

.size-btn {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    border-radius: 4px;
    padding: 0.15rem 0.45rem;
    font-size: 0.75rem;
    cursor: pointer;
}

.size-btn.active {
    background-color: var(--accent);
    color: #fff;
    border-color: var(--accent);
}

/* Gallery Grid */
.gallery-container {
    padding: 1.25rem;
    display: grid;
    gap: 1.25rem;
    flex: 1;
}

.gallery-container.grid-small {
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
}

.gallery-container.grid-medium {
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
}

.gallery-container.grid-large {
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
}

/* Image Card */
.image-card {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    overflow: hidden;
    display: flex;
    flex-direction: column;
    box-shadow: var(--card-shadow);
    cursor: pointer;
    transition: transform 0.2s, border-color 0.2s;
}

.image-card:hover {
    transform: translateY(-4px);
    border-color: var(--accent);
}

.card-thumb-wrapper {
    position: relative;
    width: 100%;
    aspect-ratio: 4 / 3;
    background-color: #0b0d13;
    overflow: hidden;
}

.card-thumb {
    width: 100%;
    height: 100%;
    object-fit: cover;
    transition: transform 0.3s;
}

.image-card:hover .card-thumb {
    transform: scale(1.04);
}

.card-badge {
    position: absolute;
    bottom: 6px;
    right: 6px;
    background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(4px);
    color: #fff;
    font-size: 0.7rem;
    padding: 2px 6px;
    border-radius: 4px;
}

.card-info {
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    flex: 1;
}

.card-title {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    line-height: 1.3;
}

.card-meta-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.75rem;
    color: var(--text-muted);
}

.card-folder {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 60%;
}

/* Table View */
.table-container {
    padding: 1.25rem;
    overflow-x: auto;
    flex: 1;
}

.metadata-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    background-color: var(--bg-surface);
    border-radius: var(--radius);
    overflow: hidden;
}

.metadata-table th,
.metadata-table td {
    padding: 0.65rem 0.85rem;
    text-align: left;
    border-bottom: 1px solid var(--border-color);
}

.metadata-table th {
    background-color: var(--bg-secondary);
    color: var(--text-secondary);
    font-weight: 600;
    user-select: none;
    cursor: pointer;
}

.metadata-table tr:hover td {
    background-color: var(--bg-hover);
}

.table-thumb {
    width: 44px;
    height: 44px;
    object-fit: cover;
    border-radius: 4px;
}

/* Pagination Bar */
.pagination-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1.25rem;
    background-color: var(--bg-secondary);
    border-top: 1px solid var(--border-color);
    flex-wrap: wrap;
    gap: 0.75rem;
}

.page-controls {
    display: flex;
    gap: 0.35rem;
}

.page-btn {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.35rem 0.75rem;
    border-radius: var(--radius);
    font-size: 0.85rem;
    cursor: pointer;
}

.page-btn.active {
    background-color: var(--accent);
    color: #fff;
    border-color: var(--accent);
}

.page-size-selector {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8rem;
    color: var(--text-muted);
}

.page-size-selector select {
    background-color: var(--bg-surface);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    padding: 0.25rem 0.5rem;
    border-radius: var(--radius);
    outline: none;
}

/* Modal / Lightbox */
.modal {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
}

.modal-backdrop {
    position: absolute;
    width: 100%;
    height: 100%;
    background-color: rgba(0, 0, 0, 0.85);
    backdrop-filter: blur(8px);
}

.modal-content {
    position: relative;
    width: 95vw;
    height: 92vh;
    background-color: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 10px 40px rgba(0,0,0,0.7);
}

.modal-header {
    height: 56px;
    padding: 0 1.25rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border-color);
}

.modal-title-area h2 {
    font-size: 1rem;
    font-weight: 700;
}

.modal-path {
    font-size: 0.75rem;
    color: var(--text-muted);
}

.modal-header-actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.close-btn {
    font-size: 1.5rem;
    width: 32px;
    height: 32px;
}

.modal-body {
    flex: 1;
    display: flex;
    min-height: 0;
}

.modal-image-wrapper {
    flex: 3;
    position: relative;
    background-color: #06080d;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
}

.image-stage {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
}

.image-stage img {
    max-width: 95%;
    max-height: 95%;
    object-fit: contain;
    transition: transform 0.1s ease-out;
    box-shadow: 0 5px 25px rgba(0,0,0,0.6);
}

.nav-btn {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    background: rgba(0, 0, 0, 0.5);
    border: none;
    color: #fff;
    font-size: 2rem;
    padding: 1rem 0.8rem;
    cursor: pointer;
    border-radius: 4px;
    transition: background 0.2s;
    user-select: none;
}

.nav-btn:hover {
    background: rgba(59, 130, 246, 0.8);
}

.prev-btn { left: 10px; }
.next-btn { right: 10px; }

.viewer-toolbar {
    position: absolute;
    bottom: 15px;
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(6px);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 0.25rem 0.75rem;
    display: flex;
    gap: 0.5rem;
}

.tool-btn {
    background: transparent;
    border: none;
    color: #fff;
    padding: 0.25rem 0.5rem;
    font-size: 0.8rem;
    cursor: pointer;
    border-radius: 4px;
}

.tool-btn:hover {
    background: var(--accent);
}

/* Metadata Panel */
.modal-metadata-panel {
    flex: 2;
    min-width: 380px;
    max-width: 480px;
    background-color: var(--bg-surface);
    border-left: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
}

.panel-tabs {
    display: flex;
    border-bottom: 1px solid var(--border-color);
    background-color: var(--bg-secondary);
}

.tab-btn {
    flex: 1;
    background: transparent;
    border: none;
    padding: 0.75rem 0.5rem;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-secondary);
    cursor: pointer;
    border-bottom: 2px solid transparent;
}

.tab-btn.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
    background-color: var(--bg-surface);
}

.tab-content {
    display: none;
    padding: 1.25rem;
    overflow-y: auto;
    flex: 1;
}

.tab-content.active {
    display: block;
}

.meta-section {
    margin-bottom: 1.25rem;
}

.meta-section h4 {
    font-size: 0.8rem;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 0.65rem;
    letter-spacing: 0.5px;
}

.meta-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 0.5rem;
}

.meta-item {
    display: flex;
    justify-content: space-between;
    padding: 0.4rem 0.6rem;
    background-color: var(--bg-secondary);
    border-radius: 4px;
    font-size: 0.82rem;
}

.meta-label {
    color: var(--text-muted);
}

.meta-value {
    font-weight: 600;
    color: var(--text-primary);
    text-align: right;
    word-break: break-all;
    max-width: 60%;
}

.panel-actions {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-top: 1rem;
}

/* Raw Exif Table */
.raw-search {
    margin-bottom: 0.75rem;
}

.raw-search input {
    width: 100%;
    background-color: var(--bg-secondary);
    border: 1px solid var(--border-color);
    padding: 0.4rem 0.6rem;
    border-radius: 4px;
    color: var(--text-primary);
    font-size: 0.85rem;
    outline: none;
}

.raw-table-wrapper {
    max-height: 400px;
    overflow-y: auto;
    border: 1px solid var(--border-color);
    border-radius: 4px;
}

.raw-exif-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.75rem;
    font-family: monospace;
}

.raw-exif-table th,
.raw-exif-table td {
    padding: 0.4rem 0.6rem;
    border-bottom: 1px solid var(--border-color);
    text-align: left;
}

.raw-exif-table th {
    background-color: var(--bg-secondary);
    color: var(--text-secondary);
}

/* Toast */
.toast {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: var(--accent);
    color: #fff;
    padding: 0.6rem 1.2rem;
    border-radius: var(--radius);
    font-size: 0.85rem;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    z-index: 2000;
}

/* Responsive */
@media (max-width: 900px) {
    .modal-body {
        flex-direction: column;
    }
    .modal-metadata-panel {
        max-width: 100%;
        min-width: 100%;
        max-height: 45%;
    }
}
"""

JS_CONTENT = """// Galerie & Dokumentation JavaScript
(function () {
    'use strict';

    // State
    const state = {
        data: window.DOCUMENTATION_DATA || { images: [], directory_tree: {}, total_images: 0 },
        filteredImages: [],
        currentFolder: '',
        searchQuery: '',
        selectedCamera: '',
        selectedYear: '',
        sortMode: 'name-asc',
        viewMode: 'grid', // 'grid' | 'table'
        gridSize: 'medium', // 'small' | 'medium' | 'large'
        pageSize: 96,
        currentPage: 1,
        activeModalIndex: -1,
        zoomLevel: 1.0,
    };

    // DOM Elements
    const elements = {
        sidebar: document.getElementById('sidebar'),
        toggleSidebarBtn: document.getElementById('toggle-sidebar-btn'),
        treeContainer: document.getElementById('tree-container'),
        resetFolderBtn: document.getElementById('reset-folder-btn'),
        searchInput: document.getElementById('search-input'),
        searchClearBtn: document.getElementById('search-clear-btn'),
        filterCamera: document.getElementById('filter-camera'),
        filterYear: document.getElementById('filter-year'),
        sortSelect: document.getElementById('sort-select'),
        resetAllFiltersBtn: document.getElementById('reset-all-filters-btn'),
        themeToggleBtn: document.getElementById('theme-toggle-btn'),
        viewGridBtn: document.getElementById('view-grid-btn'),
        viewTableBtn: document.getElementById('view-table-btn'),
        breadcrumbs: document.getElementById('breadcrumbs'),
        resultsCount: document.getElementById('results-count'),
        gridSizeControls: document.getElementById('grid-size-controls'),
        galleryContainer: document.getElementById('gallery-container'),
        tableContainer: document.getElementById('table-container'),
        tableBody: document.getElementById('table-body'),
        paginationBar: document.getElementById('pagination-bar'),
        pageControls: document.getElementById('page-controls'),
        pageInfo: document.getElementById('page-info'),
        pageSizeSelect: document.getElementById('page-size-select'),
        statCount: document.getElementById('stat-count'),
        statSize: document.getElementById('stat-size'),
        statSource: document.getElementById('stat-source'),

        // Modal
        detailModal: document.getElementById('detail-modal'),
        modalBackdrop: document.getElementById('modal-backdrop'),
        modalCloseBtn: document.getElementById('modal-close-btn'),
        modalFilename: document.getElementById('modal-filename'),
        modalPath: document.getElementById('modal-path'),
        modalImg: document.getElementById('modal-img'),
        modalPrevBtn: document.getElementById('modal-prev-btn'),
        modalNextBtn: document.getElementById('modal-next-btn'),
        modalOpenOriginal: document.getElementById('modal-open-original'),
        zoomInBtn: document.getElementById('zoom-in-btn'),
        zoomOutBtn: document.getElementById('zoom-out-btn'),
        zoomResetBtn: document.getElementById('zoom-reset-btn'),
        fullscreenBtn: document.getElementById('fullscreen-btn'),
        metaGridOverview: document.getElementById('meta-grid-overview'),
        metaGridCamSummary: document.getElementById('meta-grid-cam-summary'),
        metaGridPhoto: document.getElementById('meta-grid-photo'),
        metaGridAuthor: document.getElementById('meta-grid-author'),
        metaGridSystem: document.getElementById('meta-grid-system'),
        rawExifTbody: document.getElementById('raw-exif-tbody'),
        rawFilterInput: document.getElementById('raw-filter-input'),
        copyPathBtn: document.getElementById('copy-path-btn'),
        copyJsonBtn: document.getElementById('copy-json-btn'),
        toast: document.getElementById('toast'),
    };

    // Initialisierung
    function init() {
        if (!state.data.images || state.data.images.length === 0) {
            elements.resultsCount.innerText = 'Keine Bilddaten geladen.';
            return;
        }

        // Header Stats
        elements.statCount.innerText = state.data.total_images.toLocaleString('de-DE');
        elements.statSize.innerText = state.data.total_size_formatted || '';
        if (state.data.source_directory) {
            elements.statSource.innerText = state.data.source_directory;
        }

        // Filter Optionen befüllen
        populateFilterDropdowns();

        // Verzeichnisbaum rendern
        renderDirectoryTree();

        // Event Listeners registrieren
        registerEvents();

        // Bilder filtern und anzeigen
        applyFiltersAndSort();
    }

    function populateFilterDropdowns() {
        if (state.data.cameras) {
            state.data.cameras.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.name;
                opt.textContent = `${c.name} (${c.count})`;
                elements.filterCamera.appendChild(opt);
            });
        }
        if (state.data.years) {
            state.data.years.forEach(y => {
                const opt = document.createElement('option');
                opt.value = y.year;
                opt.textContent = `${y.year} (${y.count})`;
                elements.filterYear.appendChild(opt);
            });
        }
    }

    function renderDirectoryTree() {
        const root = state.data.directory_tree;
        if (!root) return;
        elements.treeContainer.innerHTML = '';

        function createNodeElement(node) {
            const item = document.createElement('div');
            item.className = 'tree-item';

            const row = document.createElement('div');
            row.className = 'tree-row';
            if (node.path === state.currentFolder) {
                row.classList.add('active');
            }

            const hasChildren = node.children && node.children.length > 0;
            const expander = document.createElement('span');
            expander.className = 'tree-expander';
            expander.innerHTML = hasChildren ? '&#9660;' : '&bull;';
            row.appendChild(expander);

            const icon = document.createElement('span');
            icon.className = 'tree-icon';
            icon.innerHTML = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
            row.appendChild(icon);

            const nameSpan = document.createElement('span');
            nameSpan.className = 'tree-name';
            nameSpan.textContent = node.name;
            nameSpan.title = node.path || 'Hauptverzeichnis';
            row.appendChild(nameSpan);

            const badge = document.createElement('span');
            badge.className = 'tree-badge';
            badge.textContent = node.count;
            row.appendChild(badge);

            let childrenContainer = null;
            if (hasChildren) {
                childrenContainer = document.createElement('div');
                childrenContainer.className = 'tree-children';
                node.children.forEach(child => {
                    childrenContainer.appendChild(createNodeElement(child));
                });
            }

            expander.addEventListener('click', (e) => {
                e.stopPropagation();
                if (childrenContainer) {
                    const isHidden = childrenContainer.style.display === 'none';
                    childrenContainer.style.display = isHidden ? 'block' : 'none';
                    expander.innerHTML = isHidden ? '&#9660;' : '&#9654;';
                }
            });

            row.addEventListener('click', () => {
                state.currentFolder = node.path;
                updateTreeActiveState();
                updateBreadcrumbs();
                state.currentPage = 1;
                applyFiltersAndSort();
            });

            item.appendChild(row);
            if (childrenContainer) {
                item.appendChild(childrenContainer);
            }
            return item;
        }

        elements.treeContainer.appendChild(createNodeElement(root));
    }

    function updateTreeActiveState() {
        const rows = elements.treeContainer.querySelectorAll('.tree-row');
        rows.forEach(r => {
            const name = r.querySelector('.tree-name');
            if (name) {
                const path = name.title === 'Hauptverzeichnis' ? '' : name.title;
                if (path === state.currentFolder) {
                    r.classList.add('active');
                } else {
                    r.classList.remove('active');
                }
            }
        });
    }

    function updateBreadcrumbs() {
        elements.breadcrumbs.innerHTML = '';
        const allCrumb = document.createElement('span');
        allCrumb.className = 'crumb';
        allCrumb.textContent = 'Alle Verzeichnisse';
        allCrumb.addEventListener('click', () => {
            state.currentFolder = '';
            updateTreeActiveState();
            updateBreadcrumbs();
            state.currentPage = 1;
            applyFiltersAndSort();
        });
        elements.breadcrumbs.appendChild(allCrumb);

        if (state.currentFolder) {
            const parts = state.currentFolder.split('/');
            let accumulated = '';
            parts.forEach((p, i) => {
                accumulated = accumulated ? `${accumulated}/${p}` : p;
                const sep = document.createElement('span');
                sep.textContent = ' / ';
                sep.style.color = 'var(--text-muted)';
                elements.breadcrumbs.appendChild(sep);

                const c = document.createElement('span');
                c.className = i === parts.length - 1 ? 'crumb active' : 'crumb';
                c.textContent = p;
                const targetPath = accumulated;
                if (i !== parts.length - 1) {
                    c.addEventListener('click', () => {
                        state.currentFolder = targetPath;
                        updateTreeActiveState();
                        updateBreadcrumbs();
                        state.currentPage = 1;
                        applyFiltersAndSort();
                    });
                }
                elements.breadcrumbs.appendChild(c);
            });
        }
    }

    function applyFiltersAndSort() {
        const images = state.data.images;
        const q = state.searchQuery.toLowerCase().trim();
        const cam = state.selectedCamera;
        const year = state.selectedYear;
        const folder = state.currentFolder;

        state.filteredImages = images.filter(img => {
            // Ordner-Filter
            if (folder) {
                if (img.directory !== folder && !img.directory.startsWith(folder + '/')) {
                    return false;
                }
            }

            // Kamera-Filter
            if (cam) {
                const imgCam = `${img.make || ''} ${img.model || ''}`.trim() || 'Ohne EXIF-Kamera';
                if (imgCam !== cam) return false;
            }

            // Jahr-Filter
            if (year) {
                const imgYear = img.date_original ? img.date_original.substring(0, 4) : 'Unbekannt';
                if (imgYear !== year) return false;
            }

            // Suchfeld
            if (q) {
                const matchName = img.filename.toLowerCase().includes(q);
                const matchDir = img.directory.toLowerCase().includes(q);
                const matchCam = `${img.make || ''} ${img.model || ''}`.toLowerCase().includes(q);
                const matchDate = (img.date_original || '').toLowerCase().includes(q);
                const matchArtist = (img.artist || '').toLowerCase().includes(q);
                if (!matchName && !matchDir && !matchCam && !matchDate && !matchArtist) {
                    return false;
                }
            }

            return true;
        });

        // Sortierung
        sortImages();

        // Render
        renderGallery();
        renderTable();
        renderPagination();

        elements.resultsCount.innerText = `${state.filteredImages.length.toLocaleString('de-DE')} von ${state.data.total_images.toLocaleString('de-DE')} Bildern`;
    }

    function sortImages() {
        const mode = state.sortMode;
        state.filteredImages.sort((a, b) => {
            switch (mode) {
                case 'name-asc':
                    return a.filename.localeCompare(b.filename, 'de', { numeric: true, sensitivity: 'base' });
                case 'name-desc':
                    return b.filename.localeCompare(a.filename, 'de', { numeric: true, sensitivity: 'base' });
                case 'date-desc':
                    return (b.date_original || '').localeCompare(a.date_original || '');
                case 'date-asc':
                    return (a.date_original || '').localeCompare(b.date_original || '');
                case 'size-desc':
                    return b.file_size_bytes - a.file_size_bytes;
                case 'mp-desc':
                    return b.megapixels - a.megapixels;
                default:
                    return 0;
            }
        });
    }

    function getPagedImages() {
        const start = (state.currentPage - 1) * state.pageSize;
        return state.filteredImages.slice(start, start + state.pageSize);
    }

    function renderGallery() {
        if (state.viewMode !== 'grid') {
            elements.galleryContainer.style.display = 'none';
            return;
        }
        elements.galleryContainer.style.display = 'grid';
        elements.galleryContainer.innerHTML = '';

        const paged = getPagedImages();
        if (paged.length === 0) {
            elements.galleryContainer.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: var(--text-muted);">Keine Bilder entsprechen den gewählten Filterkriterien.</div>`;
            return;
        }

        const frag = document.createDocumentFragment();
        paged.forEach((img, idx) => {
            const card = document.createElement('div');
            card.className = 'image-card';
            card.setAttribute('data-id', img.id);

            const camInfo = img.model ? `${img.model}` : '';
            const dateStr = img.date_original ? img.date_original.split(' ')[0] : '';

            card.innerHTML = `
                <div class="card-thumb-wrapper">
                    <img class="card-thumb" src="${img.url_thumbnail}" alt="${escapeHtml(img.filename)}" loading="lazy" onerror="this.onerror=null; this.src='${img.url_original}';">
                    <span class="card-badge">${img.width} &times; ${img.height}</span>
                </div>
                <div class="card-info">
                    <div class="card-title" title="${escapeHtml(img.filename)}">${escapeHtml(img.filename)}</div>
                    <div class="card-meta-row">
                        <span class="card-folder" title="${escapeHtml(img.directory)}">${escapeHtml(img.directory.split('/').pop() || 'Hauptordner')}</span>
                        <span>${img.file_size_formatted}</span>
                    </div>
                    <div class="card-meta-row">
                        <span>${camInfo}</span>
                        <span>${dateStr}</span>
                    </div>
                </div>
            `;

            card.addEventListener('click', () => {
                const realIndex = (state.currentPage - 1) * state.pageSize + idx;
                openModal(realIndex);
            });

            frag.appendChild(card);
        });

        elements.galleryContainer.appendChild(frag);
    }

    function renderTable() {
        if (state.viewMode !== 'table') {
            elements.tableContainer.style.display = 'none';
            return;
        }
        elements.tableContainer.style.display = 'block';
        elements.tableBody.innerHTML = '';

        const paged = getPagedImages();
        if (paged.length === 0) {
            elements.tableBody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 2rem; color: var(--text-muted);">Keine Bilder gefunden.</td></tr>`;
            return;
        }

        const frag = document.createDocumentFragment();
        paged.forEach((img, idx) => {
            const tr = document.createElement('tr');
            const cam = `${img.make || ''} ${img.model || ''}`.trim() || '-';
            const exp = [img.exposure_time, img.f_number, img.iso ? `ISO ${img.iso}` : ''].filter(Boolean).join(' | ') || '-';

            tr.innerHTML = `
                <td><img class="table-thumb" src="${img.url_thumbnail}" alt="" loading="lazy" onerror="this.src='${img.url_original}'"></td>
                <td style="font-weight: 600;">${escapeHtml(img.filename)}</td>
                <td style="color: var(--text-muted);">${escapeHtml(img.directory)}</td>
                <td>${img.width} &times; ${img.height} (${img.megapixels} MP)</td>
                <td>${img.file_size_formatted}</td>
                <td>${escapeHtml(cam)}</td>
                <td>${img.date_original || '-'}</td>
                <td>${exp}</td>
                <td><button class="action-btn secondary" style="padding: 0.2rem 0.5rem; font-size: 0.75rem;">Details</button></td>
            `;

            tr.addEventListener('click', () => {
                const realIndex = (state.currentPage - 1) * state.pageSize + idx;
                openModal(realIndex);
            });

            frag.appendChild(tr);
        });

        elements.tableBody.appendChild(frag);
    }

    function renderPagination() {
        const total = state.filteredImages.length;
        const totalPages = Math.ceil(total / state.pageSize) || 1;

        if (state.currentPage > totalPages) {
            state.currentPage = totalPages;
        }

        elements.pageInfo.innerText = `Seite ${state.currentPage} von ${totalPages} (${total.toLocaleString('de-DE')} Bilder)`;
        elements.pageControls.innerHTML = '';

        if (totalPages <= 1) {
            elements.paginationBar.style.display = 'none';
            return;
        }
        elements.paginationBar.style.display = 'flex';

        function createPageBtn(label, pageNum, isActive = false) {
            const btn = document.createElement('button');
            btn.className = `page-btn ${isActive ? 'active' : ''}`;
            btn.textContent = label;
            btn.addEventListener('click', () => {
                state.currentPage = pageNum;
                applyFiltersAndSort();
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
            return btn;
        }

        // Prev
        if (state.currentPage > 1) {
            elements.pageControls.appendChild(createPageBtn('« Zurück', state.currentPage - 1));
        }

        // Seiten-Buttons
        let startPage = Math.max(1, state.currentPage - 2);
        let endPage = Math.min(totalPages, state.currentPage + 2);

        if (startPage > 1) {
            elements.pageControls.appendChild(createPageBtn('1', 1));
            if (startPage > 2) {
                const dots = document.createElement('span');
                dots.textContent = '...';
                dots.style.padding = '0.3rem';
                elements.pageControls.appendChild(dots);
            }
        }

        for (let i = startPage; i <= endPage; i++) {
            elements.pageControls.appendChild(createPageBtn(i.toString(), i, i === state.currentPage));
        }

        if (endPage < totalPages) {
            if (endPage < totalPages - 1) {
                const dots = document.createElement('span');
                dots.textContent = '...';
                dots.style.padding = '0.3rem';
                elements.pageControls.appendChild(dots);
            }
            elements.pageControls.appendChild(createPageBtn(totalPages.toString(), totalPages));
        }

        // Next
        if (state.currentPage < totalPages) {
            elements.pageControls.appendChild(createPageBtn('Weiter »', state.currentPage + 1));
        }
    }

    // Modal / Lightbox Logik
    function openModal(index) {
        if (index < 0 || index >= state.filteredImages.length) return;
        state.activeModalIndex = index;
        const img = state.filteredImages[index];

        elements.modalFilename.innerText = img.filename;
        elements.modalPath.innerText = img.relative_path;

        // Bild laden (Originalbild mit hochauflösender Ansicht)
        state.zoomLevel = 1.0;
        elements.modalImg.style.transform = `scale(1.0)`;
        elements.modalImg.src = img.url_original;

        // Original-Button Link
        elements.modalOpenOriginal.onclick = () => window.open(img.url_original, '_blank');

        // Navigation Buttons Zustand
        elements.modalPrevBtn.style.visibility = index > 0 ? 'visible' : 'hidden';
        elements.modalNextBtn.style.visibility = index < state.filteredImages.length - 1 ? 'visible' : 'hidden';

        // Metadaten befüllen
        populateModalMetadata(img);

        // Anzeigen
        elements.detailModal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    function closeModal() {
        elements.detailModal.style.display = 'none';
        document.body.style.overflow = '';
        elements.modalImg.src = '';
        state.activeModalIndex = -1;
    }

    function populateModalMetadata(img) {
        // Tab 1: Übersicht
        elements.metaGridOverview.innerHTML = `
            ${renderMetaRow('Dateiname', img.filename)}
            ${renderMetaRow('Abmessungen', `${img.width} &times; ${img.height} Pixel`)}
            ${renderMetaRow('Auflösung', `${img.megapixels} Megapixel`)}
            ${renderMetaRow('Seitenverhältnis', img.aspect_ratio)}
            ${renderMetaRow('Dateigröße', img.file_size_formatted)}
            ${renderMetaRow('Format', `${img.format} (${img.color_mode})`)}
            ${renderMetaRow('DPI', (img.dpi_x && img.dpi_y) ? `${img.dpi_x} &times; ${img.dpi_y} dpi` : '-')}
        `;

        elements.metaGridCamSummary.innerHTML = `
            ${renderMetaRow('Kamera', `${img.make || ''} ${img.model || ''}`.trim() || 'Keine EXIF-Kamera')}
            ${renderMetaRow('Aufnahmedatum', img.date_original || '-')}
            ${renderMetaRow('Belichtung', [img.exposure_time, img.f_number, img.iso ? `ISO ${img.iso}` : ''].filter(Boolean).join(' | ') || '-')}
            ${renderMetaRow('Brennweite', img.focal_length || '-')}
        `;

        // Tab 2: Aufnahme & EXIF
        elements.metaGridPhoto.innerHTML = `
            ${renderMetaRow('Kamerahersteller', img.make || '-')}
            ${renderMetaRow('Kameramodell', img.model || '-')}
            ${renderMetaRow('Objektiv', img.lens || '-')}
            ${renderMetaRow('Aufnahmezeitpunkt', img.date_original || '-')}
            ${renderMetaRow('Belichtungszeit', img.exposure_time || '-')}
            ${renderMetaRow('Blendenwert', img.f_number || '-')}
            ${renderMetaRow('ISO-Empfindlichkeit', img.iso ? `ISO ${img.iso}` : '-')}
            ${renderMetaRow('Brennweite', img.focal_length || '-')}
            ${renderMetaRow('Belichtungsprogramm', img.exposure_program || '-')}
            ${renderMetaRow('Messmodus', img.metering_mode || '-')}
            ${renderMetaRow('Blitz', img.flash || '-')}
            ${renderMetaRow('Weißabgleich', img.white_balance || '-')}
            ${renderMetaRow('Farbraum', img.color_space || '-')}
        `;

        elements.metaGridAuthor.innerHTML = `
            ${renderMetaRow('Software', img.software || '-')}
            ${renderMetaRow('Künstler / Autor', img.artist || '-')}
            ${renderMetaRow('Urheberrecht', img.copyright || '-')}
            ${renderMetaRow('Beschreibung', img.description || '-')}
        `;

        // Tab 3: Datei & System
        elements.metaGridSystem.innerHTML = `
            ${renderMetaRow('Vollständiger Pfad', img.relative_path)}
            ${renderMetaRow('Dateigröße (Bytes)', `${img.file_size_bytes.toLocaleString('de-DE')} Bytes`)}
            ${renderMetaRow('Dateiendung', img.extension.toUpperCase())}
            ${renderMetaRow('Zuletzt geändert', img.modified_date)}
        `;

        // Buttons Kopier-Aktionen
        elements.copyPathBtn.onclick = () => {
            navigator.clipboard.writeText(img.relative_path);
            showToast('Dateipfad in die Zwischenablage kopiert!');
        };
        elements.copyJsonBtn.onclick = () => {
            navigator.clipboard.writeText(JSON.stringify(img, null, 2));
            showToast('Metadaten (JSON) kopiert!');
        };

        // Tab 4: Roh-EXIF
        renderRawExifTable(img.raw_exif);
    }

    function renderMetaRow(label, value) {
        return `
            <div class="meta-item">
                <span class="meta-label">${escapeHtml(label)}</span>
                <span class="meta-value">${value}</span>
            </div>
        `;
    }

    function renderRawExifTable(rawExif) {
        elements.rawExifTbody.innerHTML = '';
        if (!rawExif || Object.keys(rawExif).length === 0) {
            elements.rawExifTbody.innerHTML = `<tr><td colspan="2" style="text-align:center; color:var(--text-muted);">Keine Roh-EXIF-Daten vorhanden.</td></tr>`;
            return;
        }

        const filter = elements.rawFilterInput.value.toLowerCase().trim();
        const keys = Object.keys(rawExif).sort();

        const frag = document.createDocumentFragment();
        keys.forEach(k => {
            const v = String(rawExif[k]);
            if (filter && !k.toLowerCase().includes(filter) && !v.toLowerCase().includes(filter)) {
                return;
            }
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="color:var(--accent); font-weight:600;">${escapeHtml(k)}</td>
                <td style="word-break: break-all;">${escapeHtml(v)}</td>
            `;
            frag.appendChild(tr);
        });

        elements.rawExifTbody.appendChild(frag);
    }

    function showToast(msg) {
        elements.toast.innerText = msg;
        elements.toast.style.display = 'block';
        setTimeout(() => { elements.toast.style.display = 'none'; }, 2500);
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Events
    function registerEvents() {
        // Suche
        elements.searchInput.addEventListener('input', (e) => {
            state.searchQuery = e.target.value;
            elements.searchClearBtn.style.display = state.searchQuery ? 'block' : 'none';
            state.currentPage = 1;
            applyFiltersAndSort();
        });

        elements.searchClearBtn.addEventListener('click', () => {
            elements.searchInput.value = '';
            state.searchQuery = '';
            elements.searchClearBtn.style.display = 'none';
            state.currentPage = 1;
            applyFiltersAndSort();
        });

        // Filter
        elements.filterCamera.addEventListener('change', (e) => {
            state.selectedCamera = e.target.value;
            state.currentPage = 1;
            applyFiltersAndSort();
        });

        elements.filterYear.addEventListener('change', (e) => {
            state.selectedYear = e.target.value;
            state.currentPage = 1;
            applyFiltersAndSort();
        });

        elements.sortSelect.addEventListener('change', (e) => {
            state.sortMode = e.target.value;
            applyFiltersAndSort();
        });

        elements.resetAllFiltersBtn.addEventListener('click', () => {
            state.searchQuery = '';
            elements.searchInput.value = '';
            elements.searchClearBtn.style.display = 'none';
            state.selectedCamera = '';
            elements.filterCamera.value = '';
            state.selectedYear = '';
            elements.filterYear.value = '';
            state.sortMode = 'name-asc';
            elements.sortSelect.value = 'name-asc';
            state.currentFolder = '';
            updateTreeActiveState();
            updateBreadcrumbs();
            state.currentPage = 1;
            applyFiltersAndSort();
        });

        elements.resetFolderBtn.addEventListener('click', () => {
            state.currentFolder = '';
            updateTreeActiveState();
            updateBreadcrumbs();
            state.currentPage = 1;
            applyFiltersAndSort();
        });

        // Ansichten Umschaltung (Grid vs. Table)
        elements.viewGridBtn.addEventListener('click', () => {
            state.viewMode = 'grid';
            elements.viewGridBtn.classList.add('active');
            elements.viewTableBtn.classList.remove('active');
            elements.gridSizeControls.style.display = 'flex';
            applyFiltersAndSort();
        });

        elements.viewTableBtn.addEventListener('click', () => {
            state.viewMode = 'table';
            elements.viewTableBtn.classList.add('active');
            elements.viewGridBtn.classList.remove('active');
            elements.gridSizeControls.style.display = 'none';
            applyFiltersAndSort();
        });

        // Kachel-Größen
        const sizeBtns = elements.gridSizeControls.querySelectorAll('.size-btn');
        sizeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                sizeBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const sz = btn.getAttribute('data-size');
                elements.galleryContainer.className = `gallery-container grid-${sz}`;
            });
        });

        // Theme Toggle
        elements.themeToggleBtn.addEventListener('click', () => {
            const isDark = document.body.classList.contains('theme-dark');
            document.body.className = isDark ? 'theme-light' : 'theme-dark';
        });

        // Sidebar Toggle
        elements.toggleSidebarBtn.addEventListener('click', () => {
            elements.sidebar.classList.toggle('collapsed');
        });

        // Paging Size
        elements.pageSizeSelect.addEventListener('change', (e) => {
            state.pageSize = parseInt(e.target.value, 10);
            state.currentPage = 1;
            applyFiltersAndSort();
        });

        // Modal Close
        elements.modalCloseBtn.addEventListener('click', closeModal);
        elements.modalBackdrop.addEventListener('click', closeModal);

        // Modal Prev / Next
        elements.modalPrevBtn.addEventListener('click', () => {
            if (state.activeModalIndex > 0) {
                openModal(state.activeModalIndex - 1);
            }
        });
        elements.modalNextBtn.addEventListener('click', () => {
            if (state.activeModalIndex < state.filteredImages.length - 1) {
                openModal(state.activeModalIndex + 1);
            }
        });

        // Keyboard Navigation
        window.addEventListener('keydown', (e) => {
            if (elements.detailModal.style.display === 'flex') {
                if (e.key === 'Escape') closeModal();
                else if (e.key === 'ArrowLeft' && state.activeModalIndex > 0) openModal(state.activeModalIndex - 1);
                else if (e.key === 'ArrowRight' && state.activeModalIndex < state.filteredImages.length - 1) openModal(state.activeModalIndex + 1);
            }
        });

        // Zoom Toolbar
        elements.zoomInBtn.addEventListener('click', () => {
            state.zoomLevel = Math.min(4.0, state.zoomLevel + 0.3);
            elements.modalImg.style.transform = `scale(${state.zoomLevel})`;
        });
        elements.zoomOutBtn.addEventListener('click', () => {
            state.zoomLevel = Math.max(0.5, state.zoomLevel - 0.3);
            elements.modalImg.style.transform = `scale(${state.zoomLevel})`;
        });
        elements.zoomResetBtn.addEventListener('click', () => {
            state.zoomLevel = 1.0;
            elements.modalImg.style.transform = `scale(1.0)`;
        });
        elements.fullscreenBtn.addEventListener('click', () => {
            if (!document.fullscreenElement) {
                elements.detailModal.requestFullscreen().catch(() => {});
            } else {
                document.exitFullscreen().catch(() => {});
            }
        });

        // Tabs im Modal
        const tabBtns = document.querySelectorAll('.tab-btn');
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                tabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const targetId = btn.getAttribute('data-tab');
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                const targetContent = document.getElementById(targetId);
                if (targetContent) targetContent.classList.add('active');
            });
        });

        // Raw Filter Input
        elements.rawFilterInput.addEventListener('input', () => {
            if (state.activeModalIndex >= 0) {
                const img = state.filteredImages[state.activeModalIndex];
                renderRawExifTable(img.raw_exif);
            }
        });
    }

    // Start
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
"""


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(
        description="Erstellt eine interaktive HTML-Dokumentation für Bildsammlungen mit Galerie und Metadaten-Inspektor."
    )
    parser.add_argument(
        "--source",
        type=str,
        default=DEFAULT_SOURCE_DIR,
        help=f"Quellverzeichnis der bereinigten Bilder (Standard: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=DEFAULT_TARGET_DIR,
        help=f"Zielverzeichnis für die HTML-Dokumentation (Standard: {DEFAULT_TARGET_DIR})",
    )
    parser.add_argument(
        "--thumbnail-size",
        type=int,
        default=DEFAULT_THUMBNAIL_SIZE,
        help=f"Maximale Kantenlänge der Thumbnails in Pixeln (Standard: {DEFAULT_THUMBNAIL_SIZE})",
    )
    parser.add_argument(
        "--thumbnail-quality",
        type=int,
        default=DEFAULT_THUMBNAIL_QUALITY,
        help=f"JPEG-Qualität der Thumbnails (1-100, Standard: {DEFAULT_THUMBNAIL_QUALITY})",
    )
    parser.add_argument(
        "--no-thumbnails",
        action="store_true",
        help="Erstellung von Thumbnails überspringen.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Anzahl paralleler Worker für die Thumbnail-Erstellung (Standard: CPU-Kerne)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Ausführliche Konsolenausgaben unterdrücken.",
    )

    args = parser.parse_args()

    generate_html_documentation(
        source_dir=args.source,
        target_dir=args.target,
        thumbnail_size=args.thumbnail_size,
        thumbnail_quality=args.thumbnail_quality,
        skip_thumbnails=args.no_thumbnails,
        workers=args.workers,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
