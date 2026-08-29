import unittest
from datetime import date
from unittest.mock import patch

from update_kbo import (
    backfill_rank_history,
    build_bullpen_alert_chip,
    build_standings_from_games,
    bullpen_alert_for_game,
    completed_game_dates,
    consecutive_pitcher_names,
    format_pitcher_name,
    reconcile_completed_games,
    resolve_pitcher_identity,
)


class CompletedGameDatesTest(unittest.TestCase):
    def test_excludes_days_without_completed_games(self):
        games = [
            {"date": "2026-07-05", "completed": True},
            {"date": "2026-07-05", "completed": True},
            {"date": "2026-07-06", "completed": False},
            {"date": "2026-07-07", "completed": True},
        ]

        self.assertEqual(
            completed_game_dates(games),
            [date(2026, 7, 5), date(2026, 7, 7)],
        )


class DelayedOfficialDataTest(unittest.TestCase):
    games = [
        {
            "date": "2026-08-04",
            "away": "한화",
            "home": "삼성",
            "awayScore": 4,
            "homeScore": 1,
            "completed": True,
        },
        {
            "date": "2026-08-04",
            "away": "키움",
            "home": "롯데",
            "awayScore": 2,
            "homeScore": 3,
            "completed": True,
        },
        {
            "date": "2026-08-04",
            "away": "LG",
            "home": "SSG",
            "awayScore": 8,
            "homeScore": 10,
            "completed": True,
        },
    ]

    def test_builds_standings_from_completed_games(self):
        standings = {
            row["team"]: row for row in build_standings_from_games(self.games)
        }

        self.assertEqual(standings["한화"]["games"], 1)
        self.assertEqual(standings["한화"]["wins"], 1)
        self.assertEqual(standings["한화"]["winRate"], "1.000")
        self.assertEqual(standings["삼성"]["losses"], 1)

    def test_backfills_rank_date_when_daily_rank_api_lags(self):
        official_date = date(2026, 8, 2)
        history = {team: {official_date: 1} for team in (
            "LG", "KT", "삼성", "KIA", "두산",
            "한화", "NC", "SSG", "롯데", "키움",
        )}

        extended = backfill_rank_history(history, self.games, official_date)

        for points in extended.values():
            self.assertIn(date(2026, 8, 4), points)
        self.assertNotIn(date(2026, 8, 4), history["한화"])


class DelayedScheduleReviewTest(unittest.TestCase):
    def test_uses_finished_game_center_row_when_official_counts_match(self):
        existing_games = [
            {
                "date": "2026-08-22",
                "time": "18:00",
                "away": "LG",
                "home": "KT",
                "awayScore": 4,
                "homeScore": 3,
                "stadium": "수원",
                "completed": True,
            }
        ]
        standings = [
            {"team": "LG", "games": 1},
            {"team": "KT", "games": 1},
            {"team": "삼성", "games": 1},
            {"team": "NC", "games": 1},
        ]
        delayed_result = {
            "GAME_STATE_SC": "3",
            "CANCEL_SC_ID": "0",
            "GAME_RESULT_CK": 0,
            "G_TM": "18:00",
            "AWAY_NM": "삼성",
            "HOME_NM": "NC",
            "T_SCORE_CN": "2",
            "B_SCORE_CN": "1",
            "S_NM": "창원",
        }

        with patch("update_kbo.fetch_game_list", return_value=[delayed_result]):
            reconciled = reconcile_completed_games(
                existing_games,
                date(2026, 8, 23),
                standings,
            )

        self.assertEqual(len(reconciled), 2)
        self.assertEqual(reconciled[-1]["date"], "2026-08-23")
        self.assertEqual(reconciled[-1]["away"], "삼성")
        self.assertEqual(reconciled[-1]["homeScore"], 1)

    def test_keeps_reviewed_games_when_official_team_counts_do_not_match(self):
        existing_games = [
            {
                "date": "2026-08-22",
                "time": "18:00",
                "away": "LG",
                "home": "KT",
                "awayScore": 4,
                "homeScore": 3,
                "stadium": "수원",
                "completed": True,
            }
        ]
        standings = [
            {"team": "LG", "games": 1},
            {"team": "KT", "games": 1},
            {"team": "KIA", "games": 1},
            {"team": "키움", "games": 1},
        ]
        unrelated_result = {
            "GAME_STATE_SC": "3",
            "CANCEL_SC_ID": "0",
            "G_TM": "18:00",
            "AWAY_NM": "삼성",
            "HOME_NM": "NC",
            "T_SCORE_CN": "2",
            "B_SCORE_CN": "1",
            "S_NM": "창원",
        }

        with patch("update_kbo.fetch_game_list", return_value=[unrelated_result]):
            reconciled = reconcile_completed_games(
                existing_games,
                date(2026, 8, 23),
                standings,
            )

        self.assertIs(reconciled, existing_games)

    def test_uses_unique_subset_reflected_in_official_team_counts(self):
        standings = [
            {"team": "삼성", "games": 1},
            {"team": "NC", "games": 1},
            {"team": "한화", "games": 1},
            {"team": "SSG", "games": 1},
        ]
        delayed_results = [
            {
                "GAME_STATE_SC": "3",
                "CANCEL_SC_ID": "0",
                "G_TM": "18:00",
                "AWAY_NM": "삼성",
                "HOME_NM": "NC",
                "T_SCORE_CN": "2",
                "B_SCORE_CN": "1",
                "S_NM": "창원",
            },
            {
                "GAME_STATE_SC": "3",
                "CANCEL_SC_ID": "0",
                "G_TM": "18:00",
                "AWAY_NM": "한화",
                "HOME_NM": "SSG",
                "T_SCORE_CN": "4",
                "B_SCORE_CN": "3",
                "S_NM": "문학",
            },
            {
                "GAME_STATE_SC": "3",
                "CANCEL_SC_ID": "0",
                "G_TM": "18:00",
                "AWAY_NM": "KIA",
                "HOME_NM": "키움",
                "T_SCORE_CN": "5",
                "B_SCORE_CN": "0",
                "S_NM": "고척",
            },
        ]

        with patch("update_kbo.fetch_game_list", return_value=delayed_results):
            reconciled = reconcile_completed_games(
                [],
                date(2026, 8, 29),
                standings,
            )

        self.assertEqual(len(reconciled), 2)
        self.assertEqual(
            {(game["away"], game["home"]) for game in reconciled},
            {("삼성", "NC"), ("한화", "SSG")},
        )


class ConsecutivePitcherNamesTest(unittest.TestCase):
    appearances = {"테스트투수": {}}

    def test_sunday_and_tuesday_are_not_consecutive(self):
        actual = consecutive_pitcher_names(
            date(2026, 6, 28),
            date(2026, 6, 30),
            self.appearances,
            self.appearances,
        )

        self.assertEqual(actual, set())

    def test_tuesday_and_wednesday_are_consecutive(self):
        actual = consecutive_pitcher_names(
            date(2026, 6, 30),
            date(2026, 7, 1),
            self.appearances,
            self.appearances,
        )

        self.assertEqual(actual, {"테스트투수"})

    def test_rained_out_wednesday_breaks_consecutive_days(self):
        actual = consecutive_pitcher_names(
            date(2026, 6, 30),
            date(2026, 7, 2),
            self.appearances,
            self.appearances,
        )

        self.assertEqual(actual, set())

    def test_same_name_different_player_keys_are_not_consecutive(self):
        actual = consecutive_pitcher_names(
            date(2026, 7, 7),
            date(2026, 7, 8),
            {"player:60146": {"name": "이승현"}},
            {"player:51454": {"name": "이승현"}},
        )

        self.assertEqual(actual, set())


class PitcherIdentityTest(unittest.TestCase):
    players = [
        {
            "P_ID": "51454",
            "P_NM": "이승현",
            "BACK_NO": "57",
            "POS_NO": "투수",
            "T_NM": "삼성",
        },
        {
            "P_ID": "60146",
            "P_NM": "이승현",
            "BACK_NO": "26",
            "POS_NO": "투수",
            "T_NM": "삼성",
        },
    ]

    def test_same_name_pitcher_is_resolved_by_detail_game_log(self):
        def game_logs(player_id):
            if str(player_id) == "51454":
                return [
                    {
                        "date": "2026-07-08",
                        "opponent": "LG",
                        "innings": "2 1/3",
                        "batters": "8",
                    }
                ]
            return [
                {
                    "date": "2026-07-07",
                    "opponent": "LG",
                    "innings": "1",
                    "batters": "3",
                }
            ]

        with patch("update_kbo.active_team_pitchers", return_value=self.players):
            with patch("update_kbo.fetch_pitcher_game_logs", side_effect=game_logs):
                identity = resolve_pitcher_identity(
                    "이승현",
                    "삼성",
                    "2026-07-08",
                    "LG",
                    {"innings": "2 1/3", "batters": "8", "pitches": "30"},
                    3,
                )

        self.assertEqual(identity["key"], "player:51454")
        self.assertEqual(identity["playerId"], "51454")

    def test_unresolved_same_name_pitcher_gets_non_matching_key(self):
        with patch("update_kbo.active_team_pitchers", return_value=self.players):
            with patch("update_kbo.fetch_pitcher_game_logs", return_value=[]):
                identity = resolve_pitcher_identity(
                    "이승현",
                    "삼성",
                    "2026-07-08",
                    "LG",
                    {"innings": "2 1/3", "batters": "8", "pitches": "30"},
                    3,
                )

        self.assertEqual(identity["key"], "ambiguous:삼성:이승현:2026-07-08:3")
        self.assertFalse(identity["identityMatched"])


class BullpenAlertForGameTest(unittest.TestCase):
    def test_two_consecutive_appearances_are_hidden_before_tuesday_game(self):
        alert = bullpen_alert_for_game(
            {"name": "테스트투수", "consecutive": True, "heavyLastGame": False},
            date(2026, 6, 30),
            date(2026, 6, 28),
        )

        self.assertIsNone(alert)

    def test_two_consecutive_appearances_are_shown_before_next_day_game(self):
        alert = bullpen_alert_for_game(
            {"name": "테스트투수", "consecutive": True, "heavyLastGame": False},
            date(2026, 6, 29),
            date(2026, 6, 28),
        )

        self.assertIsNotNone(alert)
        self.assertTrue(alert["consecutive"])

    def test_thirty_pitch_appearance_is_hidden_after_monday_off_day(self):
        alert = bullpen_alert_for_game(
            {
                "name": "테스트투수",
                "consecutive": False,
                "heavyLastGame": True,
                "lastGameDate": "2026-06-28",
            },
            date(2026, 6, 30),
            date(2026, 6, 28),
        )

        self.assertIsNone(alert)


class PitcherNameFormatTest(unittest.TestCase):
    def test_pitcher_name_keeps_name_only(self):
        self.assertEqual(format_pitcher_name("테스트투수"), "테스트투수")

    def test_bullpen_chip_displays_name_without_back_number(self):
        html = build_bullpen_alert_chip(
            {
                "name": "테스트투수",
                "consecutive": True,
                "firstInnings": "1",
                "firstPitches": "12",
                "latestInnings": "1",
                "latestPitches": "10",
            },
            "2026-07-07",
            "2026-07-08",
        )

        self.assertIn("테스트투수<small>", html)
        self.assertNotIn("#", html)


if __name__ == "__main__":
    unittest.main()
