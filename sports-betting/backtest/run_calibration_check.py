"""Roda `calibration.calibration_report` sobre todos os CSVs em `HISTORICAL_DATA_DIR` e imprime
o resultado — a mesma checagem cujos resultados estão documentados em
`docs/estrategias_extraidas_livros.md`, item 3. Não importa `config.py` de propósito (que exige
credenciais via `.env`) — este script não precisa de nenhuma delas, só do diretório de CSVs.

Uso:
    python -m backtest.run_calibration_check [diretório, padrão data/historical]
"""
from __future__ import annotations

import sys
from pathlib import Path

from backtest.calibration import calibration_report, split_train_test
from data.historical_loader import load_matches_from_csv

_MIN_MATCHES = 200  # CSV menor que isso não tem dado suficiente pra separar treino/teste


def main() -> None:
    hist_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/historical")

    for csv_path in sorted(hist_dir.glob("*.csv")):
        matches = load_matches_from_csv(csv_path)
        if len(matches) < _MIN_MATCHES:
            print(f"{csv_path.name}: só {len(matches)} jogos, pulando")
            continue

        train, test = split_train_test(matches, test_fraction=0.2)
        bins = calibration_report(train, test, half_life_days=1095, bin_size=0.1, min_bin_size=15)

        print(f"\n=== {csv_path.name} ({len(matches)} jogos, treino={len(train)}, teste={len(test)}) ===")
        for b in sorted(bins, key=lambda b: (b.outcome, b.prob_low)):
            print(
                f"  {b.outcome:10s} [{b.prob_low:.1f}-{b.prob_high:.1f}) n={b.n:4d}  "
                f"previsto={b.predicted_avg:.3f}  observado={b.observed_rate:.3f}  gap={b.gap:+.3f}"
            )


if __name__ == "__main__":
    main()
