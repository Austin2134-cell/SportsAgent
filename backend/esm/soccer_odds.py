"""
Soccer odds helpers — posted DNB lines, juice ceiling, play validation.
"""

import re
from typing import Optional

WC_JUICE_CEILING = -130  # American odds; -131 and worse (e.g. -240) exceed ceiling


def is_dnb_bet(bet_text: str) -> bool:
    t = (bet_text or "").lower()
    return "draw no bet" in t or re.search(r"\bdnb\b", t)


def parse_dnb_team(bet_text: str) -> Optional[str]:
    """Extract team name from 'Draw No Bet — Germany' style labels."""
    m = re.search(r"(?:draw no bet|dnb)\s*[—\-–:]?\s*(.+)$", bet_text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def parse_game_matchup(game_str: str) -> Optional[tuple[str, str]]:
    """Return (away_team, home_team) from 'Away vs Home' game string."""
    g = re.sub(r"\s*\([^)]+\)\s*$", "", (game_str or "").strip())
    for sep in (" vs ", " @ ", " at ", " v "):
        if sep in g.lower():
            parts = re.split(re.escape(sep), g, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
    return None


def _team_matches(picked: str, team: str) -> bool:
    a = (picked or "").strip().lower()
    b = (team or "").strip().lower()
    return a == b or a in b or b in a


def within_juice_ceiling(american_odds: int) -> bool:
    """True if odds are -130 or better (e.g. -120, +138 pass; -240 fails)."""
    return int(american_odds) >= WC_JUICE_CEILING


def find_game_in_snapshot(snapshot: dict, game_str: str) -> Optional[dict]:
    matchup = parse_game_matchup(game_str)
    if not matchup:
        return None
    away_q, home_q = matchup
    for sport_data in snapshot.get("sports", {}).values():
        for game in sport_data.get("games", []):
            away = game.get("away_team", "")
            home = game.get("home_team", "")
            if _team_matches(away_q, away) and _team_matches(home_q, home):
                return game
            if _team_matches(away_q, home) and _team_matches(home_q, away):
                return game
    return None


def posted_dnb_odds(game: dict, team: str) -> Optional[int]:
    """Return posted draw_no_bet American odds for team, or None if unavailable."""
    lines = game.get("lines", {})
    home = game.get("home_team", "")
    away = game.get("away_team", "")
    if _team_matches(team, home):
        return lines.get("home_dnb")
    if _team_matches(team, away):
        return lines.get("away_dnb")
    return None


def validate_wc_official_plays(card: dict, snapshot: dict) -> dict:
    """
    Enforce data integrity: DNB plays must use posted draw_no_bet lines from the API.
    Removes DNB plays with no posted line or juice worse than -130.
    Syncs totals odds to posted API lines when a matching game is found.
    """
    plays = list(card.get("official_plays") or [])
    kept: list[dict] = []
    removed_notes: list[str] = []

    for play in plays:
        bet = play.get("bet", "")
        game_row = find_game_in_snapshot(snapshot, play.get("game", ""))

        if is_dnb_bet(bet):
            team = parse_dnb_team(bet)
            if not team or not game_row:
                removed_notes.append(f"Removed DNB (no game match): {bet}")
                continue
            posted = posted_dnb_odds(game_row, team)
            if posted is None:
                removed_notes.append(
                    f"Removed DNB {team}: no posted draw_no_bet line in API"
                )
                continue
            if not within_juice_ceiling(posted):
                removed_notes.append(
                    f"Removed DNB {team}: posted line {posted} exceeds -130 ceiling"
                )
                continue
            lines = game_row.get("lines", {})
            play["odds"] = int(posted)
            play["book"] = (lines.get("dnb_book") or "draftkings").replace("_", " ").title()
            if play["book"].lower() == "draftkings":
                play["book"] = "DraftKings"
            play["market"] = "draw_no_bet"
            kept.append(play)
            continue

        # Totals — align odds to API when available
        if game_row and "total" in bet.lower():
            lines = game_row.get("lines", {})
            if "under" in bet.lower() and lines.get("under_odds") is not None:
                play["odds"] = int(lines["under_odds"])
            elif "over" in bet.lower() and lines.get("over_odds") is not None:
                play["odds"] = int(lines["over_odds"])
            if lines.get("total_book"):
                play["book"] = lines["total_book"].replace("_", " ").title()

        kept.append(play)

    if removed_notes:
        pass_notes = list(card.get("pass_notes") or [])
        for note in removed_notes:
            print(f"[wc_runner] {note}")
            pass_notes.append(note)
        card["pass_notes"] = pass_notes

    card["official_plays"] = kept
    return card
