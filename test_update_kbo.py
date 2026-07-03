import unittest
from datetime import date

from update_kbo import bullpen_alert_for_game, consecutive_pitcher_names


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

if __name__ == "__main__":
    unittest.main()
