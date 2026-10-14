"""Offline smoke tests for the football manager backend (does not need a Telegram token)."""
from pathlib import Path
import tempfile
import career_multileague as ml
import career_economy as eco


def run():
    original = ml.DB_PATH
    test_db = Path(tempfile.gettempdir()) / "football_manager_smoke_test.sqlite3"
    test_db.unlink(missing_ok=True)
    ml.DB_PATH = test_db
    try:
        ml.install()
        eco.install()
        generated = ml.seed_generated_squads()
        leagues = ml.league_list()
        assert len(leagues) == 7, f"expected 7 leagues, got {len(leagues)}"
        assert generated > 0
        for league in leagues:
            club_rows = ml.clubs(league["id"])
            assert club_rows
            assert all(len(ml.squad(club["id"])) == 23 for club in club_rows)
            assert ml.generate_fixtures(league["id"], league["season"]) > 0
        league = leagues[0]
        club = ml.clubs(league["id"])[0]
        player_before = ml.squad(club["id"])[0]
        for rnd in range(1, 39):
            eco.simulate_league_round(league["id"], rnd, league["season"])
        ok, msg = eco.finish_season(league["id"], league["season"])
        assert ok, msg
        player_after = eco.player_profile(player_id=player_before["id"])
        assert player_after["age"] == player_before["age"] + 1
        ok_again, _ = eco.finish_season(league["id"], league["season"])
        assert not ok_again, "repeat season closure should be blocked"
        assert eco.player_leaderboard(5), "player stats leaderboard should exist after match simulation"
        print("PASS: 7 leagues, 23-player squads, schedules, match stats, age progression, duplicate-close protection")
    finally:
        ml.DB_PATH = original
        test_db.unlink(missing_ok=True)
        # SQLite may create sidecar files when the connection closes.
        Path(str(test_db) + "-wal").unlink(missing_ok=True)
        Path(str(test_db) + "-shm").unlink(missing_ok=True)


if __name__ == "__main__":
    run()
