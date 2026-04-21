def compute_tilt_score(max_y_spreads):
    """
    Compute the tilt test score.
    Args:
        max_y_spreads (list of float): Maximum Y-spread at each waypoint.
    Returns:
        float: The score (higher is better, max 40 if perfect alignment).
    """
    if not max_y_spreads or len(max_y_spreads) != 2:
        raise ValueError("Expected two max_y_spread values (one per waypoint)")
    return 40.0 - max_y_spreads[0] - max_y_spreads[1]
