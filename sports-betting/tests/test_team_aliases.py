from data.team_aliases import TEAM_ALIASES, normalize_team_name


def test_known_alias_is_translated():
    assert normalize_team_name("Botafogo") == "Botafogo-RJ"
    assert normalize_team_name("Vasco da Gama") == "Vasco"


def test_unknown_name_passes_through_unchanged():
    assert normalize_team_name("Flamengo") == "Flamengo"
    assert normalize_team_name("Time Inexistente") == "Time Inexistente"


def test_all_aliases_map_to_a_different_name():
    # um alias que mapeia pro mesmo nome seria inútil e sinal de erro de digitação
    for odds_api_name, csv_name in TEAM_ALIASES.items():
        assert odds_api_name != csv_name
