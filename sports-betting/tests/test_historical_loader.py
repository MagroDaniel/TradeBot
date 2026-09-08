from datetime import date

import pytest

from data.historical_loader import load_matches_from_csv


def test_loads_football_data_co_uk_format(tmp_path):
    csv_path = tmp_path / "european.csv"
    csv_path.write_text(
        "HomeTeam,AwayTeam,FTHG,FTAG\n"
        "Arsenal,Chelsea,2,1\n"
        "Chelsea,Arsenal,0,0\n",
        encoding="utf-8",
    )

    matches = load_matches_from_csv(csv_path)

    assert len(matches) == 2
    assert matches[0].home_team == "Arsenal"
    assert matches[0].away_team == "Chelsea"
    assert matches[0].home_goals == 2
    assert matches[0].away_goals == 1


def test_loads_brasileirao_dataset_format(tmp_path):
    csv_path = tmp_path / "brasileirao.csv"
    csv_path.write_text(
        "mandante,visitante,mandante_Placar,visitante_Placar\n"
        "Flamengo,Vasco,3,1\n"
        "Vasco,Flamengo,1,1\n",
        encoding="utf-8",
    )

    matches = load_matches_from_csv(csv_path)

    assert len(matches) == 2
    assert matches[0].home_team == "Flamengo"
    assert matches[0].away_team == "Vasco"
    assert matches[0].home_goals == 3
    assert matches[0].away_goals == 1


def test_unrecognized_format_raises(tmp_path):
    csv_path = tmp_path / "unknown.csv"
    csv_path.write_text("col_a,col_b\n1,2\n", encoding="utf-8")

    with pytest.raises(ValueError):
        load_matches_from_csv(csv_path)


def test_skips_malformed_rows(tmp_path):
    csv_path = tmp_path / "brasileirao.csv"
    csv_path.write_text(
        "mandante,visitante,mandante_Placar,visitante_Placar\n"
        "Flamengo,Vasco,3,1\n"
        "Gremio,Internacional,,2\n"  # placar do mandante ausente
        "Santos,Sao Paulo,1,0\n",
        encoding="utf-8",
    )

    matches = load_matches_from_csv(csv_path)

    assert len(matches) == 2
    assert [m.home_team for m in matches] == ["Flamengo", "Santos"]


def test_parses_date_column_brasileirao_dataset(tmp_path):
    csv_path = tmp_path / "brasileirao.csv"
    csv_path.write_text(
        "data,mandante,visitante,mandante_Placar,visitante_Placar\n"
        "29/03/2003,Guarani,Vasco,4,2\n",
        encoding="utf-8",
    )

    matches = load_matches_from_csv(csv_path)

    assert matches[0].match_date == date(2003, 3, 29)


def test_parses_date_column_football_data_co_uk(tmp_path):
    csv_path = tmp_path / "european.csv"
    csv_path.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG\n"
        "15/08/2023,Arsenal,Chelsea,2,1\n",
        encoding="utf-8",
    )

    matches = load_matches_from_csv(csv_path)

    assert matches[0].match_date == date(2023, 8, 15)


def test_missing_date_column_leaves_match_date_none(tmp_path):
    csv_path = tmp_path / "european.csv"
    csv_path.write_text("HomeTeam,AwayTeam,FTHG,FTAG\nArsenal,Chelsea,2,1\n", encoding="utf-8")

    matches = load_matches_from_csv(csv_path)

    assert matches[0].match_date is None


def test_unparseable_date_leaves_match_date_none_but_keeps_row(tmp_path):
    csv_path = tmp_path / "european.csv"
    csv_path.write_text(
        "Date,HomeTeam,AwayTeam,FTHG,FTAG\ndata-invalida,Arsenal,Chelsea,2,1\n", encoding="utf-8"
    )

    matches = load_matches_from_csv(csv_path)

    assert len(matches) == 1
    assert matches[0].match_date is None
