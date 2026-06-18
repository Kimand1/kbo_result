#!/usr/bin/env python3
"""Refresh the embedded 2026 KBO data in index.html from official KBO sources."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_URL = "https://www.koreabaseball.com"
SEASON = 2026
SEASON_START = date(SEASON, 3, 28)
INDEX_PATH = Path(__file__).with_name("index.html")

TEAM_COLORS = {
    "LG": "#f92776",
    "KT": "#6f58a8",
    "삼성": "#0061b2",
    "KIA": "#02abba",
    "두산": "#0c0d28",
    "한화": "#529e01",
    "NC": "#af917b",
    "SSG": "#e0002a",
    "롯데": "#fb7e32",
    "키움": "#777777",
}

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
}


def request_text(path: str) -> str:
    request = urllib.request.Request(BASE_URL + path, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def post_json(path: str, data: dict[str, str], referer: str) -> dict:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    headers = {
        **REQUEST_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": BASE_URL + referer,
    }
    request = urllib.request.Request(
        BASE_URL + path, data=payload, headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def clean_cell(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_standings(page: str) -> list[dict[str, object]]:
    table_match = re.search(
        r'<table summary="순위, 팀명,승,패,무,승률,승차,최근10경기,연속,홈,방문".*?'
        r"<tbody>(.*?)</tbody>",
        page,
        re.DOTALL,
    )
    if not table_match:
        raise RuntimeError("KBO standings table was not found")

    standings = []
    for row_html in re.findall(r"<tr>(.*?)</tr>", table_match.group(1), re.DOTALL):
        cells = [
            clean_cell(cell)
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        ]
        if len(cells) < 8:
            continue
        standings.append(
            {
                "rank": int(cells[0]),
                "team": cells[1],
                "games": int(cells[2]),
                "wins": int(cells[3]),
                "losses": int(cells[4]),
                "draws": int(cells[5]),
                "winRate": cells[6].removeprefix("0"),
                "gamesBehind": cells[7],
            }
        )

    if len(standings) != 10:
        raise RuntimeError(f"Expected 10 standings rows, found {len(standings)}")
    return standings


def fetch_rank_history(end_date: date) -> tuple[date, dict[str, dict[date, int]]]:
    response = post_json(
        "/ws/Record.asmx/GetTeamRankDaily",
        {
            "startDate": SEASON_START.strftime("%Y%m%d"),
            "endDate": end_date.strftime("%Y%m%d"),
        },
        "/Record/TeamRank/GraphDaily.aspx",
    )
    if response.get("result_cd") != "100":
        raise RuntimeError(f"KBO rank API failed: {response}")

    history: dict[str, dict[date, int]] = {}
    latest_date = SEASON_START
    for series in response["data"]:
        points: dict[date, int] = {}
        for year, zero_based_month, day, rank in series["data"]:
            point_date = date(year, zero_based_month + 1, day)
            points[point_date] = rank
            latest_date = max(latest_date, point_date)
        history[series["name"]] = points

    if set(history) != set(TEAM_COLORS):
        raise RuntimeError(f"Unexpected KBO teams in rank API: {sorted(history)}")
    return latest_date, history


def month_range(start: date, end: date):
    current = start.replace(day=1)
    while current <= end:
        yield current
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def span_texts(fragment: str) -> list[str]:
    values = re.findall(r"<span(?:\s+class=\"[^\"]*\")?>(.*?)</span>", fragment)
    return [clean_cell(value) for value in values]


def fetch_games(end_date: date) -> list[dict[str, object]]:
    games = []
    for month in month_range(SEASON_START, end_date):
        response = post_json(
            "/ws/Schedule.asmx/GetScheduleList",
            {
                "leId": "1",
                "srIdList": "0,9,6",
                "seasonId": str(SEASON),
                "gameMonth": month.strftime("%m"),
                "teamId": "",
            },
            "/Schedule/Schedule.aspx",
        )
        current_date: date | None = None
        for row_data in response.get("rows", []):
            cells = row_data["row"]
            if cells[0].get("Class") == "day":
                day_match = re.match(r"(\d{2})\.(\d{2})", cells[0]["Text"])
                if not day_match:
                    continue
                current_date = date(
                    SEASON, int(day_match.group(1)), int(day_match.group(2))
                )
                offset = 1
            else:
                offset = 0

            if current_date is None or not (SEASON_START <= current_date <= end_date):
                continue

            game_parts = span_texts(cells[offset + 1]["Text"])
            if len(game_parts) != 5:
                continue
            away, away_score, versus, home_score, home = game_parts
            if versus != "vs" or not away_score.isdigit() or not home_score.isdigit():
                continue

            games.append(
                {
                    "date": current_date.isoformat(),
                    "time": clean_cell(cells[offset]["Text"]),
                    "away": away,
                    "home": home,
                    "awayScore": int(away_score),
                    "homeScore": int(home_score),
                    "stadium": clean_cell(cells[offset + 6]["Text"]),
                    "completed": True,
                }
            )

    games.sort(key=lambda game: (game["date"], game["time"], game["stadium"]))
    return games


def build_rank_data(
    standings: list[dict[str, object]],
    latest_date: date,
    history: dict[str, dict[date, int]],
    games: list[dict[str, object]],
) -> dict[str, object]:
    label_dates = []
    current = SEASON_START
    while current <= latest_date:
        label_dates.append(current)
        current += timedelta(days=1)
    labels = [current.isoformat() for current in label_dates]

    datasets = []
    ranks_by_team: dict[str, list[int]] = {}
    for team, points in history.items():
        ranks = []
        latest_rank = None
        for current in label_dates:
            if current in points:
                latest_rank = points[current]
            if latest_rank is None:
                raise RuntimeError(f"No starting rank found for {team}")
            ranks.append(latest_rank)
        ranks_by_team[team] = ranks
        datasets.append(
            {
                "label": team,
                "borderColor": TEAM_COLORS[team],
                "backgroundColor": TEAM_COLORS[team],
                "data": ranks,
                "pointRadius": 0,
                "pointHoverRadius": 5,
                "borderWidth": 2,
                "tension": 0.15,
                "fill": False,
                "spanGaps": True,
            }
        )

    games_by_date: dict[date, list[dict[str, object]]] = defaultdict(list)
    for game in games:
        games_by_date[date.fromisoformat(str(game["date"]))].append(game)

    records = {team: {"wins": 0, "losses": 0, "draws": 0} for team in history}
    games_behind_by_team = {team: [] for team in history}
    for index, current in enumerate(label_dates):
        for game in games_by_date[current]:
            away = str(game["away"])
            home = str(game["home"])
            away_score = int(game["awayScore"])
            home_score = int(game["homeScore"])
            if away_score == home_score:
                records[away]["draws"] += 1
                records[home]["draws"] += 1
            elif away_score > home_score:
                records[away]["wins"] += 1
                records[home]["losses"] += 1
            else:
                records[away]["losses"] += 1
                records[home]["wins"] += 1

        leaders = [
            team for team, ranks in ranks_by_team.items() if ranks[index] == 1
        ]
        if not leaders:
            raise RuntimeError(f"No first-place team found for {current.isoformat()}")
        leader = max(
            leaders,
            key=lambda team: records[team]["wins"] - records[team]["losses"],
        )
        leader_record = records[leader]

        for team in history:
            if ranks_by_team[team][index] == 1:
                games_behind = 0.0
            else:
                games_behind = (
                    leader_record["wins"]
                    - records[team]["wins"]
                    + records[team]["losses"]
                    - leader_record["losses"]
                ) / 2
            games_behind_by_team[team].append(max(0.0, games_behind))

    games_behind_datasets = [
        {
            "label": team,
            "borderColor": TEAM_COLORS[team],
            "backgroundColor": TEAM_COLORS[team],
            "data": games_behind_by_team[team],
            "pointRadius": 0,
            "pointHoverRadius": 5,
            "borderWidth": 2,
            "tension": 0.15,
            "fill": False,
            "spanGaps": True,
        }
        for team in history
    ]

    for row in standings:
        team = str(row["team"])
        standings_value = str(row["gamesBehind"])
        expected = 0.0 if standings_value in {"", "-"} else float(standings_value)
        actual = games_behind_by_team[team][-1]
        if actual != expected:
            raise RuntimeError(
                f"Games behind for {team} is {actual}, standings show {expected}"
            )

    return {
        "title": f"{SEASON} KBO 팀별 일별 순위",
        "generatedAtKst": datetime.now(ZoneInfo("Asia/Seoul")).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "sourcePage": BASE_URL + "/Record/TeamRank/GraphDaily.aspx",
        "sourceApi": BASE_URL + "/ws/Record.asmx/GetTeamRankDaily",
        "scheduleApi": BASE_URL + "/ws/Schedule.asmx/GetScheduleList",
        "note": "무경기일은 직전 공식 순위와 게임차를 유지해 일별 라벨을 채웠습니다.",
        "seasonStart": SEASON_START.isoformat(),
        "chartEndDate": latest_date.isoformat(),
        "latestOfficialDate": latest_date.isoformat(),
        "labels": labels,
        "datasets": datasets,
        "gamesBehindDatasets": games_behind_datasets,
        "latest": [
            {
                "team": row["team"],
                "color": TEAM_COLORS[str(row["team"])],
                "rank": row["rank"],
            }
            for row in standings
        ],
    }


def build_rank_rows(standings: list[dict[str, object]]) -> str:
    rows = []
    for row in standings:
        team = str(row["team"])
        rows.append(
            f'''
          <tr class="rank-row" data-team="{team}" tabindex="0" aria-label="{team} 선택">
            <td><input class="team-filter" type="checkbox" value="{team}" aria-label="{team} 경기 보기"></td>
            <td>{row["rank"]}위</td>
            <td><span class="team-cell"><span class="swatch" style="background:{TEAM_COLORS[team]}"></span>{team}</span></td>
            <td>{row["wins"]}</td>
            <td>{row["losses"]}</td>
            <td>{row["draws"]}</td>
            <td>{row["winRate"]}</td>
            <td>{row["gamesBehind"]}</td>
          </tr>'''
        )
    return "".join(rows)


def build_matchups(
    games: list[dict[str, object]], standings: list[dict[str, object]]
) -> tuple[str, str]:
    teams = [str(row["team"]) for row in standings]
    records = {
        team: {opponent: [0, 0, 0] for opponent in teams if opponent != team}
        for team in teams
    }
    totals = defaultdict(lambda: [0, 0, 0])

    for game in games:
        away = str(game["away"])
        home = str(game["home"])
        away_score = int(game["awayScore"])
        home_score = int(game["homeScore"])
        if away_score == home_score:
            records[away][home][2] += 1
            records[home][away][2] += 1
            totals[away][2] += 1
            totals[home][2] += 1
        elif away_score > home_score:
            records[away][home][0] += 1
            records[home][away][1] += 1
            totals[away][0] += 1
            totals[home][1] += 1
        else:
            records[away][home][1] += 1
            records[home][away][0] += 1
            totals[away][1] += 1
            totals[home][0] += 1

    for row in standings:
        team = str(row["team"])
        expected = [row["wins"], row["losses"], row["draws"]]
        if totals[team] != expected:
            raise RuntimeError(
                f"Schedule totals for {team} are {totals[team]}, standings are {expected}"
            )

    header_cells = "".join(
        f"<th>{team}<br><span>승-패-무</span></th>" for team in teams
    )
    header = f"""
          <tr>
            <th>팀</th>
            {header_cells}
            <th>합계</th>
          </tr>"""

    body_rows = []
    for team in teams:
        cells = []
        for opponent in teams:
            if opponent == team:
                cells.append('<td class="self-cell">-</td>')
                continue
            wins, losses, draws = records[team][opponent]
            class_name = "good" if wins > losses else "bad" if wins < losses else "even"
            cells.append(
                f'<td class="{class_name}">{wins}-{losses}-{draws}</td>'
            )
        wins, losses, draws = totals[team]
        body_rows.append(
            f'''
          <tr>
            <th><span class="team-cell"><span class="swatch" style="background:{TEAM_COLORS[team]}"></span>{team}</span></th>
            {"".join(cells)}
            <td class="total-cell">{wins}-{losses}-{draws}</td>
          </tr>'''
        )
    return header, "".join(body_rows)


def replace_exactly_once(text: str, pattern: str, replacement: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"Expected one replacement for pattern: {pattern[:80]}")
    return updated


def update_html(
    page: str,
    standings: list[dict[str, object]],
    games: list[dict[str, object]],
    rank_data: dict[str, object],
) -> str:
    latest_date = str(rank_data["latestOfficialDate"])
    page = replace_exactly_once(
        page,
        r'(<table class="rank-table">.*?<tbody>)\s*.*?(\s*</tbody>)',
        lambda_match(r"\1", build_rank_rows(standings), r"\2"),
    )

    matchup_header, matchup_body = build_matchups(games, standings)
    page = replace_exactly_once(
        page,
        r'(<table class="matchup-table">\s*<thead>)\s*.*?(\s*</thead>\s*<tbody>)'
        r"\s*.*?(\s*</tbody>)",
        lambda_match(r"\1", matchup_header, r"\2", matchup_body, r"\3"),
    )
    page = re.sub(
        rf"{SEASON}-\d{{2}}-\d{{2}} 완료 경기 기준",
        f"{latest_date} 완료 경기 기준",
        page,
        count=1,
    )

    compact_json = lambda value: json.dumps(
        value, ensure_ascii=False, separators=(",", ":")
    )
    constants = (
        f"    const RANK_CHART_DATA = {compact_json(rank_data)};\n"
        f"    const RECENT_GAMES = {compact_json(games)};\n"
        f"    const TEAM_FILTER_ORDER = "
        f"{compact_json([row['team'] for row in standings])};"
    )
    page = replace_exactly_once(
        page,
        r"    const RANK_CHART_DATA = .*?;\s*"
        r"const RECENT_GAMES = .*?;\s*"
        r"const TEAM_FILTER_ORDER = .*?;",
        constants,
    )
    return page


def lambda_match(*parts: str) -> str:
    """Join replacement parts; backreferences are expanded by re.sub."""
    return "".join(parts)


def main() -> None:
    today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date()
    standings_page = request_text("/Record/TeamRank/TeamRank.aspx")
    standings = parse_standings(standings_page)
    latest_date, history = fetch_rank_history(today_kst)
    games = fetch_games(latest_date)
    rank_data = build_rank_data(standings, latest_date, history, games)

    original = INDEX_PATH.read_text(encoding="utf-8")
    updated = update_html(original, standings, games, rank_data)
    INDEX_PATH.write_text(updated, encoding="utf-8")
    print(
        f"Updated {INDEX_PATH.name} through {latest_date.isoformat()}: "
        f"{len(games)} completed games"
    )


if __name__ == "__main__":
    main()
