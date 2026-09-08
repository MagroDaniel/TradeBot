"""Orquestração diária do bot: resolve os resultados de ontem e envia os picks de hoje.

Pensado para rodar 1x por dia (ex: 8h da manhã) via cron / GitHub Actions.
Ordem de execução: resultados de ontem primeiro, depois picks de hoje —
exatamente como decidido para o envio no Telegram.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import config
from alerts.telegram_notifier import TelegramNotifier
from analysis.ev import calculate_ev
from analysis.kelly import capped_stake
from data.historical_loader import load_matches_from_csv
from data.odds_client import OddsAPIClient
from model.poisson_model import PoissonModel
from storage.picks_store import Pick, PicksStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def resolve_yesterday(client: OddsAPIClient, store: PicksStore, notifier: TelegramNotifier) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    picks = store.load_picks(yesterday)
    if not picks:
        logger.info("Nenhum pick registrado para %s", yesterday)
        return

    sport_keys = {p.market.split(":", 1)[0] for p in picks}
    scores_by_event: dict[str, dict] = {}
    for sport_key in sport_keys:
        try:
            for event in client.get_scores(sport_key, days_from=3):
                scores_by_event[event["id"]] = event
        except Exception:
            logger.exception("Falha ao buscar placares para %s", sport_key)

    for pick in picks:
        event = scores_by_event.get(pick.event_id)
        if not event or not event.get("completed"):
            continue
        won = _pick_won(pick, event)
        pick.result = "green" if won else "red"
        pick.profit_units = (
            pick.suggested_stake_fraction * (pick.odds - 1)
            if won
            else -pick.suggested_stake_fraction
        )

    store.update_results(yesterday, picks)
    notifier.send_results_summary(yesterday, picks)


def _pick_won(pick: Pick, event: dict) -> bool:
    scores = {
        s["name"]: int(s["score"])
        for s in event.get("scores", []) or []
        if s.get("score") is not None
    }
    home_goals = scores.get(pick.home_team)
    away_goals = scores.get(pick.away_team)
    if home_goals is None or away_goals is None:
        return False

    if pick.selection == f"{pick.home_team} vence":
        return home_goals > away_goals
    if pick.selection == f"{pick.away_team} vence":
        return away_goals > home_goals
    if pick.selection == "Empate":
        return home_goals == away_goals
    if pick.selection == "Over 2.5 gols":
        return (home_goals + away_goals) > 2
    if pick.selection == "Under 2.5 gols":
        return (home_goals + away_goals) <= 2
    return False


def build_todays_picks(client: OddsAPIClient, model: PoissonModel) -> list[Pick]:
    picks: list[Pick] = []
    sport_keys = [s.strip() for s in config.SPORT_KEYS.split(",") if s.strip()]

    for sport_key in sport_keys:
        try:
            events = client.get_upcoming_odds(sport_key)
        except Exception:
            logger.exception("Falha ao buscar odds para %s", sport_key)
            continue

        for event in events:
            picks.extend(_evaluate_event(event, model, sport_key))

    return picks


def _evaluate_event(event: dict, model: PoissonModel, sport_key: str) -> list[Pick]:
    home_team = event["home_team"]
    away_team = event["away_team"]

    try:
        probs = model.match_probabilities(home_team, away_team)
    except KeyError:
        logger.warning("Sem histórico calibrado para %s x %s — pulando", home_team, away_team)
        return []

    best_odds = _best_odds_by_selection(event)
    selection_prob_map = {
        f"{home_team} vence": probs["home_win"],
        "Empate": probs["draw"],
        f"{away_team} vence": probs["away_win"],
        "Over 2.5 gols": probs["over_2_5"],
        "Under 2.5 gols": probs["under_2_5"],
    }

    candidates: list[Pick] = []
    for selection, model_prob in selection_prob_map.items():
        odds = best_odds.get(selection)
        if odds is None:
            continue

        ev = calculate_ev(model_prob, odds)
        if ev < config.EV_THRESHOLD:
            continue

        stake = capped_stake(model_prob, odds, config.KELLY_FRACTION, config.MAX_STAKE_FRACTION)
        if stake <= 0:
            continue

        candidates.append(
            Pick(
                event_id=event["id"],
                match=f"{home_team} x {away_team}",
                home_team=home_team,
                away_team=away_team,
                commence_time=event["commence_time"],
                market=f"{sport_key}:1x2/totals",
                selection=selection,
                odds=odds,
                model_probability=model_prob,
                ev=ev,
                suggested_stake_fraction=stake,
            )
        )

    return candidates


def _best_odds_by_selection(event: dict) -> dict[str, float]:
    """Melhor odd disponível entre as casas de apostas para cada seleção do evento."""
    home_team = event["home_team"]
    away_team = event["away_team"]
    best: dict[str, float] = {}

    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            for outcome in market.get("outcomes", []):
                name = outcome["name"]
                price = outcome["price"]

                if market["key"] == "h2h":
                    if name == home_team:
                        selection = f"{home_team} vence"
                    elif name == away_team:
                        selection = f"{away_team} vence"
                    else:
                        selection = "Empate"
                elif market["key"] == "totals" and outcome.get("point") == 2.5:
                    selection = "Over 2.5 gols" if name == "Over" else "Under 2.5 gols"
                else:
                    continue

                if selection not in best or price > best[selection]:
                    best[selection] = price

    return best


def main() -> None:
    client = OddsAPIClient(
        api_key=config.ODDS_API_KEY,
        regions=config.REGIONS,
        markets=config.MARKETS,
    )
    store = PicksStore(config.STORAGE_PATH)
    notifier = TelegramNotifier(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)

    # 1) resultados de ontem primeiro
    resolve_yesterday(client, store, notifier)

    # 2) depois, os picks de hoje
    model = PoissonModel()
    historical_matches = load_matches_from_csv(config.HISTORICAL_DATA_PATH)
    model.fit(historical_matches)

    today = date.today().isoformat()
    picks = build_todays_picks(client, model)
    store.save_picks(today, picks)
    notifier.send_daily_picks(today, picks)


if __name__ == "__main__":
    main()
