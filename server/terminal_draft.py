"""Prepare an editable Codex composer draft, never a submitted command."""
import re


def draft_when_ready(state, output):
    if not state.get('draft'):
        return None
    state['draft_screen'] = (state.get('draft_screen', b'') + output)[-16384:]
    screen = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', state['draft_screen'])
    # Wait for the composer footer, not merely terminal initialization: login
    # and trust dialogs must be completed by the user before inserting text.
    if not any(label in screen.lower() for label in (b'for shortcuts', b'context left', b'context remaining')):
        return None
    text = state.pop('draft')
    state.pop('draft_screen', None)
    # Bracketed paste preserves multiline text in the composer. No trailing
    # CR or LF is sent outside the paste, so only the user can submit it.
    text = ''.join(c for c in text if c in '\n\t' or ord(c) >= 32).replace('\x7f', '')
    return b'\x1b[200~' + text.encode() + b'\x1b[201~'
