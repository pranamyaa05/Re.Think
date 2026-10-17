# Re.Think
Re.Th!nk() : A competitive programming companion that tracks your growth and guides your thinking without giving away solutions.

## Known Limitations
- **Coach Rate Limiter:** The coach message rate limiter (`_user_last_coach_message` in `app/services/coach.py`) is held in-process memory. It resets upon application restart and does not synchronize across multiple app instances or worker processes. This is suitable for single-instance deployment; use Redis or a distributed store if scaling horizontally.
