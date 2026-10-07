# Export functionality for match data.

import csv
import json
import logging
from datetime import UTC, tzinfo
from pathlib import Path
from typing import Any

from valorant_matches.scraping.matches import Match

logger = logging.getLogger("valorant_matches")

EXPORT_FIELDS = [
    "date_time",
    "start_time",
    "team1",
    "team2",
    "score",
    "countdown",
    "status",
    "url",
]


def match_to_dict(match: Match, zone: tzinfo | None = None) -> dict[str, Any]:
    """Convert a match to export values.

    Args:
        match: Match to export.
        zone: Timezone for the human-readable date_time; None means local.

    Returns:
        A dictionary keyed by EXPORT_FIELDS; start_time is ISO 8601 UTC.
    """
    date, time = match.local_date_time(zone)
    return {
        "date_time": f"{date} {time}",
        "start_time": match.starts_at.astimezone(UTC).isoformat()
        if match.starts_at
        else None,
        "team1": match.team1,
        "team2": match.team2,
        "score": match.score,
        "countdown": match.countdown,
        "status": match.status,
        "url": match.url,
    }


def export_json(
    matches: list[Match], output_path: str | Path, zone: tzinfo | None = None
) -> int:
    """Export matches to a JSON file.

    Args:
        matches: Matches to export.
        output_path: Path to output file.
        zone: Timezone for date_time values.

    Returns:
        Number of matches exported.
    """
    rows = [match_to_dict(match, zone) for match in matches]

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"matches": rows, "count": len(rows)}, indent=2), encoding="utf-8"
    )

    logger.info(f"Exported {len(rows)} matches to {output_path}")
    return len(rows)


def export_csv(
    matches: list[Match], output_path: str | Path, zone: tzinfo | None = None
) -> int:
    """Export matches to a CSV file.

    Args:
        matches: Matches to export.
        output_path: Path to output file.
        zone: Timezone for date_time values.

    Returns:
        Number of matches exported.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(match_to_dict(match, zone) for match in matches)

    logger.info(f"Exported {len(matches)} matches to {output_path}")
    return len(matches)


def export_matches(
    matches: list[Match],
    export_format: str,
    output_path: str | Path | None = None,
    zone: tzinfo | None = None,
) -> int:
    """Export matches in the requested format.

    Args:
        matches: Matches to export.
        export_format: "json" or "csv".
        output_path: Output file; defaults to matches.<format>.
        zone: Timezone for date_time values.

    Returns:
        Number of matches exported.

    Raises:
        ValueError: For an unsupported format.
    """
    if output_path is None:
        output_path = f"matches.{export_format}"

    if export_format == "json":
        return export_json(matches, output_path, zone)
    if export_format == "csv":
        return export_csv(matches, output_path, zone)
    raise ValueError(f"Unsupported export format: {export_format}")
