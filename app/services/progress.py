from datetime import date
from ..models import UoMType, CheckIn, Goal


def compute_progress_score(goal: Goal, check_in: CheckIn) -> float:
    """Compute system progress score based on UoM type."""
    uom = goal.uom_type

    if uom in (UoMType.NUMERIC_MIN, UoMType.PERCENT_MIN):
        # Higher is better: Achievement ÷ Target
        if not goal.target_value or goal.target_value == 0:
            return 0.0
        actual = check_in.actual_value or 0
        score = (actual / goal.target_value) * 100
        return min(round(score, 2), 150.0)  # cap at 150%

    elif uom in (UoMType.NUMERIC_MAX, UoMType.PERCENT_MAX):
        # Lower is better: Target ÷ Achievement
        actual = check_in.actual_value
        if not actual or actual == 0:
            return 0.0
        if not goal.target_value:
            return 0.0
        score = (goal.target_value / actual) * 100
        return min(round(score, 2), 150.0)

    elif uom == UoMType.TIMELINE:
        # Date-based: on or before deadline = 100%
        if not goal.target_date or not check_in.actual_date:
            return 0.0
        if check_in.actual_date <= goal.target_date:
            # Days saved bonus
            days_saved = (goal.target_date - check_in.actual_date).days
            return min(100.0 + days_saved * 0.5, 110.0)
        else:
            days_late = (check_in.actual_date - goal.target_date).days
            score = max(100.0 - days_late * 2, 0.0)
            return round(score, 2)

    elif uom == UoMType.ZERO_BASED:
        # Zero = success
        actual = check_in.actual_value
        if actual is None:
            return 0.0
        return 100.0 if actual == 0 else 0.0

    return 0.0


def get_weighted_score(goals_with_checkins: list) -> float:
    """Compute weighted overall score across all goals."""
    total_weightage = 0
    weighted_sum = 0

    for goal, check_in in goals_with_checkins:
        if check_in and check_in.progress_score is not None:
            weighted_sum += check_in.progress_score * (goal.weightage / 100)
            total_weightage += goal.weightage

    if total_weightage == 0:
        return 0.0
    return round(weighted_sum, 2)
