from datetime import time

def reservation_slot_label(reservation, day):
    """Return a human label (Matin/Après-midi/Journée) for reservation on given day."""
    morning_start = time(8, 0)
    morning_end = time(12, 0)
    afternoon_start = time(13, 0)
    afternoon_end = time(17, 0)
    day_date = day.date()
    start_date = reservation.start_at.date()
    end_date = reservation.end_at.date()
    start_time = reservation.start_at.time()
    end_time = reservation.end_at.time()

    if start_date == day_date and end_date == day_date:
        if start_time >= morning_start and end_time <= morning_end:
            return "Matin"
        if start_time >= afternoon_start and end_time <= afternoon_end:
            return "Après-midi"
        return "Journée"
    if start_date == day_date:
        if start_time >= afternoon_start:
            return "Après-midi"
        return "Journée"
    if end_date == day_date:
        if end_time <= morning_end:
            return "Matin"
        return "Journée"
    return "Journée"
