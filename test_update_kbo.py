import unittest
from datetime import date
from unittest.mock import patch

from update_kbo import (
    build_bullpen_alert_chip,
    bullpen_alert_for_game,
    consecutive_pitcher_names,
    format_pitcher_name,
    resolve_pitcher_identity,
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
