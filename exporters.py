# Export functionality for match data.

import csv
import json
import logging
from pathlib import Path

from match_extractor import Match

logger = logging.getLogger("valorant_matches")


def match_to_dict(match: Match) -> dict:
    """Convert a Match object to a dictionary for export."""
    if match.is_live:
        status = "live"
    elif match.is_upcoming:
        status = "upcoming"
    else:
        status = "completed"

    return {
        "date_time": f"{match.date} {match.time}",
        "team1": match.team1,
        "team2": match.team2,
        "score": match.score,
        "status": status,
        "url": match.url,
    }


def export_json(results: list[tuple[dict, Match]], output_path: str | Path) -> int:
    """Export match results to JSON file.

    Args:
        results: List of (link, Match) tuples
        output_path: Path to output file

    Returns:
        Number of matches exported
    """
    matches = [match_to_dict(match) for _, match in results]

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"matches": matches, "count": len(matches)}, f, indent=2)

    logger.info(f"Exported {len(matches)} matches to {output_path}")
    return len(matches)


def export_csv(results: list[tuple[dict, Match]], output_path: str | Path) -> int:
    """Export match results to CSV file.

    Args:
        results: List of (link, Match) tuples
        output_path: Path to output file

    Returns:
        Number of matches exported
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["date_time", "team1", "team2", "score", "status", "url"]

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for _, match in results:
            writer.writerow(match_to_dict(match))

    logger.info(f"Exported {len(results)} matches to {output_path}")
    return len(results)


def export_matches(
    results: list[tuple[dict, Match]],
    format: str,
    output_path: str | Path | None = None,
) -> int:
    """Export match results to specified format.

    Args:
        results: List of (link, Match) tuples
        format: Export format ('json' or 'csv')
        output_path: Optional path to output file. If not provided, uses default.

    Returns:
        Number of matches exported
    """
    if output_path is None:
        output_path = f"matches.{format}"

    if format == "json":
        return export_json(results, output_path)
    elif format == "csv":
        return export_csv(results, output_path)
    else:
        raise ValueError(f"Unsupported export format: {format}")
