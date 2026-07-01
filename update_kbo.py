#!/usr/bin/env python3
"""Refresh the embedded 2026 KBO data in index.html from official KBO sources."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


BASE_URL = "https://www.koreabaseball.com"
SEASON = 2026
SEASON_START = date(SEASON, 3, 28)
INDEX_PATH = Path(__file__).with_name("index.html")
KST = timezone(timedelta(hours=9), name="KST")

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

GAME_LIST_SERIES = "0,1,3,4,5,6,7,8,9"
WEEKDAY_NAMES = ("월", "화", "수", "목", "금", "토", "일")


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
            relay_html = str(cells[offset + 2].get("Text") or "")
            has_review = re.search(
                r"\bid\s*=\s*(['\"])btnReview\1", relay_html, re.IGNORECASE
            )
            if (
                versus != "vs"
                or not away_score.isdigit()
                or not home_score.isdigit()
                or not has_review
            ):
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


def fetch_game_list(game_date: date) -> list[dict[str, object]]:
    response = post_json(
        "/ws/Main.asmx/GetKboGameList",
        {
            "leId": "1",
            "srId": GAME_LIST_SERIES,
            "date": game_date.strftime("%Y%m%d"),
        },
        f"/Schedule/GameCenter/Main.aspx?gameDate={game_date.strftime('%Y%m%d')}",
    )
    if response.get("code") != "100":
        raise RuntimeError(f"KBO game list API failed for {game_date}: {response}")

    return [
        game
        for game in response.get("game", [])
        if int(game.get("SR_ID", -1)) == 0
    ]


def fetch_next_games(start_date: date) -> list[dict[str, object]]:
    for offset in range(15):
        game_date = start_date + timedelta(days=offset)
        scheduled = [
            game
            for game in fetch_game_list(game_date)
            if str(game.get("GAME_STATE_SC")) == "1"
            and str(game.get("CANCEL_SC_ID")) == "0"
        ]
        if not scheduled:
            continue

        next_games = []
        for game in scheduled:
            game_id = str(game["G_ID"])
            next_games.append(
                {
                    "date": game_date.isoformat(),
                    "time": clean_cell(str(game.get("G_TM") or "")),
                    "stadium": clean_cell(str(game.get("S_NM") or "")),
                    "away": clean_cell(str(game.get("AWAY_NM") or "")),
                    "home": clean_cell(str(game.get("HOME_NM") or "")),
                    "awayStarter": clean_cell(str(game.get("T_PIT_P_NM") or "")),
                    "homeStarter": clean_cell(str(game.get("B_PIT_P_NM") or "")),
                    "gameId": game_id,
                    "previewUrl": (
                        BASE_URL
                        + "/Schedule/GameCenter/Main.aspx?"
                        + urllib.parse.urlencode(
                            {
                                "gameDate": game_date.strftime("%Y%m%d"),
                                "gameId": game_id,
                                "section": "START_PIT",
                            }
                        )
                    ),
                }
            )
        return sorted(
            next_games,
            key=lambda game: (str(game["time"]), str(game["stadium"])),
        )

    return []


def fetch_relief_appearances(
    game: dict[str, object],
) -> dict[str, dict[str, dict[str, str]]]:
    game_id = str(game["G_ID"])
    response = post_json(
        "/ws/Schedule.asmx/GetBoxScoreScroll",
        {
            "leId": "1",
            "srId": "0",
            "seasonId": str(SEASON),
            "gameId": game_id,
        },
        (
            "/Schedule/GameCenter/Main.aspx?"
            + urllib.parse.urlencode(
                {
                    "gameDate": game_id[:8],
                    "gameId": game_id,
                    "section": "REVIEW",
                }
            )
        ),
    )
    if response.get("code") != "100":
        raise RuntimeError(f"KBO box score API failed for {game_id}: {response}")

    team_names = [
        clean_cell(str(game.get("AWAY_NM") or "")),
        clean_cell(str(game.get("HOME_NM") or "")),
    ]
    pitcher_tables = response.get("arrPitcher", [])
    if len(pitcher_tables) != 2:
        raise RuntimeError(
            f"Expected two pitcher tables for {game_id}, found {len(pitcher_tables)}"
        )

    appearances: dict[str, dict[str, dict[str, str]]] = {
        team: {} for team in team_names
    }
    for team, pitcher_table in zip(team_names, pitcher_tables):
        table = json.loads(pitcher_table["table"])
        for row_data in table.get("rows", []):
            cells = [
                clean_cell(str(cell.get("Text") or ""))
                for cell in row_data.get("row", [])
            ]
            if len(cells) < 9 or cells[1] == "선발":
                continue
            appearances[team][cells[0]] = {
                "innings": cells[6],
                "pitches": cells[8],
            }
    return appearances


def pitch_count_value(value: object) -> int:
    match = re.search(r"\d+", str(value).replace(",", ""))
    return int(match.group()) if match else 0


def fetch_completed_games(game_date: date) -> list[dict[str, object]]:
    return [
        game
        for game in fetch_game_list(game_date)
        if str(game.get("GAME_STATE_SC")) == "3"
        and int(game.get("GAME_RESULT_CK", 0)) == 1
    ]


def fetch_bullpen_alerts(latest_date: date) -> dict[str, object]:
    first_date = latest_date - timedelta(days=1)
    appearances_by_date: dict[
        date, dict[str, dict[str, dict[str, str]]]
    ] = {
        first_date: {team: {} for team in TEAM_COLORS},
        latest_date: {team: {} for team in TEAM_COLORS},
    }
    appearances_by_game: dict[str, dict[str, dict[str, dict[str, str]]]] = {}

    def get_relief_appearances(
        game: dict[str, object],
    ) -> dict[str, dict[str, dict[str, str]]]:
        game_id = str(game["G_ID"])
        if game_id not in appearances_by_game:
            appearances_by_game[game_id] = fetch_relief_appearances(game)
        return appearances_by_game[game_id]

    for game_date in (first_date, latest_date):
        for game in fetch_completed_games(game_date):
            for team, appearances in get_relief_appearances(game).items():
                appearances_by_date[game_date][team].update(appearances)

    last_game_by_team: dict[str, dict[str, object] | None] = {
        team: None for team in TEAM_COLORS
    }
    search_date = latest_date
    stop_date = max(SEASON_START, latest_date - timedelta(days=15))
    while search_date >= stop_date and any(
        game is None for game in last_game_by_team.values()
    ):
        completed_games = sorted(
            fetch_completed_games(search_date),
            key=lambda game: (
                str(game.get("G_TM") or ""),
                str(game.get("S_NM") or ""),
                str(game.get("G_ID") or ""),
            ),
            reverse=True,
        )
        for game in completed_games:
            game_appearances = get_relief_appearances(game)
            for team in (
                clean_cell(str(game.get("AWAY_NM") or "")),
                clean_cell(str(game.get("HOME_NM") or "")),
            ):
                if team in last_game_by_team and last_game_by_team[team] is None:
                    last_game_by_team[team] = {
                        "date": search_date.isoformat(),
                        "appearances": game_appearances.get(team, {}),
                    }
        search_date -= timedelta(days=1)

    teams: dict[str, list[dict[str, object]]] = {}
    for team in TEAM_COLORS:
        first_appearances = appearances_by_date[first_date][team]
        latest_appearances = appearances_by_date[latest_date][team]
        consecutive_names = set(first_appearances) & set(latest_appearances)
        last_game = last_game_by_team[team] or {
            "date": "",
            "appearances": {},
        }
        last_game_appearances = last_game["appearances"]
        heavy_names = {
            name
            for name, appearance in last_game_appearances.items()
            if pitch_count_value(appearance["pitches"]) >= 30
        }

        alerts = []
        for name in sorted(consecutive_names | heavy_names, key=lambda name: name):
            alert = {
                "name": name,
                "consecutive": name in consecutive_names,
                "heavyLastGame": name in heavy_names,
            }
            if name in consecutive_names:
                alert.update(
                    {
                        "firstInnings": first_appearances[name]["innings"],
                        "firstPitches": first_appearances[name]["pitches"],
                        "latestInnings": latest_appearances[name]["innings"],
                        "latestPitches": latest_appearances[name]["pitches"],
                    }
                )
            if name in heavy_names:
                last_appearance = last_game_appearances[name]
                alert.update(
                    {
                        "lastGameDate": str(last_game["date"]),
                        "lastGameInnings": last_appearance["innings"],
                        "lastGamePitches": last_appearance["pitches"],
                    }
                )
            alerts.append(alert)
        teams[team] = alerts

    return {
        "firstDate": first_date.isoformat(),
        "latestDate": latest_date.isoformat(),
        "teams": teams,
    }


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
    win_loss_margin_by_team = {team: [] for team in history}
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
            win_loss_margin_by_team[team].append(
                records[team]["wins"] - records[team]["losses"]
            )
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

    win_loss_margin_datasets = [
        {
            "label": team,
            "borderColor": TEAM_COLORS[team],
            "backgroundColor": TEAM_COLORS[team],
            "data": win_loss_margin_by_team[team],
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
        expected_margin = int(row["wins"]) - int(row["losses"])
        actual_margin = win_loss_margin_by_team[team][-1]
        if actual_margin != expected_margin:
            raise RuntimeError(
                f"Win-loss margin for {team} is {actual_margin}, "
                f"standings show {expected_margin}"
            )

    return {
        "title": f"{SEASON} KBO 팀별 일별 순위",
        "generatedAtKst": datetime.now(KST).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "sourcePage": BASE_URL + "/Record/TeamRank/GraphDaily.aspx",
        "sourceApi": BASE_URL + "/ws/Record.asmx/GetTeamRankDaily",
        "scheduleApi": BASE_URL + "/ws/Schedule.asmx/GetScheduleList",
        "note": "무경기일은 직전 공식 순위, 게임차, 승패 마진을 유지해 일별 라벨을 채웠습니다.",
        "seasonStart": SEASON_START.isoformat(),
        "chartEndDate": latest_date.isoformat(),
        "latestOfficialDate": latest_date.isoformat(),
        "labels": labels,
        "datasets": datasets,
        "gamesBehindDatasets": games_behind_datasets,
        "winLossMarginDatasets": win_loss_margin_datasets,
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


def build_next_games_section(
    next_games: list[dict[str, object]],
    bullpen_alerts: dict[str, object],
) -> str:
    first_date = str(bullpen_alerts["firstDate"])
    latest_date = str(bullpen_alerts["latestDate"])
    team_relievers = bullpen_alerts["teams"]

    cards = []
    for game in next_games:
        game_date = date.fromisoformat(str(game["date"]))
        date_label = (
            f"{game_date.isoformat()} ({WEEKDAY_NAMES[game_date.weekday()]})"
        )
        team_blocks = []
        for side, team, starter in (
            ("원정", str(game["away"]), str(game["awayStarter"])),
            ("홈", str(game["home"]), str(game["homeStarter"])),
        ):
            relievers = team_relievers.get(team, [])
            if relievers:
                reliever_html = "".join(
                    build_bullpen_alert_chip(reliever, first_date, latest_date)
                    for reliever in relievers
                )
            else:
                reliever_html = '<span class="bullpen-none">없음</span>'

            starter_name = starter or "미발표"
            team_blocks.append(
                f'''
            <div class="next-team" style="--team-color:{TEAM_COLORS[team]}">
              <div class="next-team-heading">
                <span class="game-side">{side}</span>
                <strong>{html.escape(team)}</strong>
              </div>
              <dl class="game-detail-list">
                <div>
                  <dt>예고 선발</dt>
                  <dd>{html.escape(starter_name)}</dd>
                </div>
                <div>
                  <dt>연투·30구 불펜</dt>
                  <dd class="bullpen-list">{reliever_html}</dd>
                </div>
              </dl>
            </div>'''
            )

        cards.append(
            f'''
        <article class="next-game-card">
          <div class="next-game-meta">
            <strong>{date_label} {html.escape(str(game["time"]))}</strong>
            <span>{html.escape(str(game["stadium"]))}</span>
          </div>
          <div class="next-matchup" aria-label="{html.escape(str(game["away"]))} 대 {html.escape(str(game["home"]))}">
            <strong>{html.escape(str(game["away"]))}</strong>
            <span>vs</span>
            <strong>{html.escape(str(game["home"]))}</strong>
          </div>
          <div class="next-team-grid">
{"".join(team_blocks)}
          </div>
          <a class="preview-link" href="{html.escape(str(game["previewUrl"]))}" target="_blank" rel="noreferrer">KBO 프리뷰</a>
        </article>'''
        )

    if next_games:
        next_date = str(next_games[0]["date"])
        grid = f'<div class="next-games-grid">{"".join(cards)}</div>'
        meta = f"{next_date} 예정 경기 · 예고 선발은 KBO 등록 기준"
    else:
        grid = '<p class="empty-next-games">향후 14일 내 예정된 정규시즌 경기가 없습니다.</p>'
        meta = "예정 경기 없음"

    return f'''<!-- NEXT_GAMES_START -->
    <section class="next-games-panel" aria-labelledby="nextGamesTitle">
      <div class="section-heading">
        <div>
          <h2 id="nextGamesTitle">다음 경기 일정 · 예고 선발 · 불펜 체크</h2>
          <p class="section-meta">{meta}</p>
        </div>
      </div>
      {grid}
      <p class="footnote">
        불펜 체크는 {first_date}와 {latest_date} 일자 모두 공식 박스스코어에 구원 등판한 투수와,
        연투 여부와 무관하게 해당 팀 전경기에 30구 이상 던진 구원 투수를 표시합니다. 출처:
        <a href="{BASE_URL}/Schedule/GameCenter/Main.aspx" target="_blank" rel="noreferrer">KBO 게임센터</a>
      </p>
    </section>
    <!-- NEXT_GAMES_END -->'''


def build_bullpen_alert_chip(
    reliever: dict[str, object],
    first_date: str,
    latest_date: str,
) -> str:
    title_parts = []
    small_parts = []
    if reliever.get("consecutive"):
        title_parts.append(
            f'2연투: {first_date} '
            f'{reliever["firstInnings"]}이닝 {reliever["firstPitches"]}구, '
            f'{latest_date} '
            f'{reliever["latestInnings"]}이닝 {reliever["latestPitches"]}구'
        )
        small_parts.append("2연투")
    if reliever.get("heavyLastGame"):
        title_parts.append(
            f'전경기 30구+: {reliever["lastGameDate"]} '
            f'{reliever["lastGameInnings"]}이닝 {reliever["lastGamePitches"]}구'
        )
        small_parts.append(f'{reliever["lastGamePitches"]}구')

    title = " / ".join(title_parts)
    small = " · ".join(small_parts)
    return (
        '<span class="bullpen-chip" '
        f'title="{html.escape(title)}">'
        f'{html.escape(str(reliever["name"]))}'
        f'<small>{html.escape(small)}</small></span>'
    )


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
    next_games: list[dict[str, object]],
    bullpen_alerts: dict[str, object],
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
    page = replace_exactly_once(
        page,
        r"<!-- NEXT_GAMES_START -->.*?<!-- NEXT_GAMES_END -->",
        build_next_games_section(next_games, bullpen_alerts),
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
    today_kst = datetime.now(KST).date()
    standings_page = request_text("/Record/TeamRank/TeamRank.aspx")
    standings = parse_standings(standings_page)
    latest_date, history = fetch_rank_history(today_kst)
    games = fetch_games(latest_date)
    rank_data = build_rank_data(standings, latest_date, history, games)
    next_games = fetch_next_games(today_kst)
    bullpen_alerts = fetch_bullpen_alerts(latest_date)

    original = INDEX_PATH.read_text(encoding="utf-8")
    updated = update_html(
        original,
        standings,
        games,
        rank_data,
        next_games,
        bullpen_alerts,
    )
    INDEX_PATH.write_text(updated, encoding="utf-8")
    next_games_summary = (
        f", next games on {next_games[0]['date']}" if next_games else ""
    )
    print(
        f"Updated {INDEX_PATH.name} through {latest_date.isoformat()}: "
        f"{len(games)} completed games{next_games_summary}"
    )


if __name__ == "__main__":
    main()
