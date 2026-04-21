"""
analyze_results.py — Main entry point for results analysis.

Loads trial data and provides options for leaderboard display and visualization.
"""

from analyze_io import load_all_trials, load_gen_summaries
from analyze_leaderboard import print_leaderboard
from analyze_plotting import plot_combined


def main() -> None:
    """
    Load trial results and display leaderboard and visualization plots.

    Inputs:
        None

    Returns:
        None
    """
    print("[load] Loading trial data...")
    records = load_all_trials()
    summaries = load_gen_summaries()

    if not records:
        print("[error] No trial data found in trials directory.")
        return

    print(f"[load] Loaded {len(records)} trials from {len(summaries)} generations")

    # Display leaderboard
    print_leaderboard(records)

    # Display plots
    try:
        print("[plot] Opening visualization... (close window to exit)")
        plot_combined(records, summaries)
    except Exception as e:
        print(f"[warn] Could not open plot window: {e}")


if __name__ == "__main__":
    main()
