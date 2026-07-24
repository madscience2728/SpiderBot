"""
picrawler_fixes.py -- targeted patches for bugs found in the upstream
`picrawler` library (github.com/sunfounder/picrawler), applied at import
time rather than forking the whole package. Import and call apply() once,
before instantiating Picrawler().

Why a patch module instead of a full fork: we only found one confirmed
bug in the actual gait logic. Forking the whole library means we stop
getting any future upstream fixes (servo tuning, new poses, etc.) for
free. A surgical monkeypatch gets us the fix with none of that cost --
if upstream ever fixes it themselves, this patch becomes a harmless
no-op (still overwrites their fixed version with our identical fix).

--- BUG: turn_right's rear-right leg target ---
picrawler/picrawler.py, MoveList.turn_right (compare against MoveList.
turn_left, its mirror image): the rear-right leg's target coordinate is
written as [TURN_X1, TURN_X1, ...] -- TURN_X1 used for BOTH x and y --
instead of [TURN_X1, TURN_Y1, ...]. TURN_Y1 is never referenced in
turn_right at all. Confirmed by direct comparison with turn_left, whose
equivalent leg correctly pairs TURN_X0/TURN_Y0 throughout.

Effect: verified against the un-patched library (see chat) -- the
rear-right leg barely moves off its resting position during turn_right
(stays near [45,45,...] the whole gait) instead of swinging out to meet
its partner leg's target the way turn_left's legs correctly do in pairs.
That leg ends up dragging/bound against the ground while the other three
try to pivot the body -- a plausible source of servo strain/current
spikes, and a likely contributor to the I2C stalls we saw specifically
on 'turn right' (see relay_server.py's HARDWARE_TIMEOUT handling for the
software-side mitigation for that).

Verified fix output (rear-right leg, all 3 mid-turn rows): now correctly
matches its partner leg's [TURN_X1, TURN_Y1] target, exactly mirroring
how turn_left's rear pair share [TURN_X0, TURN_Y0].
"""

from picrawler import Picrawler

_applied = False


def apply():
    global _applied
    if _applied:
        return
    _applied = True

    MoveList = Picrawler.MoveList

    @property
    @MoveList.check_stand
    @MoveList.normal_action(1)
    def turn_right_fixed(self):
        return [
            [[self.X_DEFAULT, self.Y_DEFAULT, self.z_current], [self.X_TURN, self.Y_START, self.Z_UP], [self.X_DEFAULT, self.Y_START, self.z_current], [self.X_DEFAULT, self.Y_DEFAULT, self.z_current]],
            [[self.TURN_X0, self.TURN_Y0, self.z_current], [self.TURN_X0, self.TURN_Y0, self.Z_UP], [self.TURN_X1, self.TURN_Y1, self.z_current], [self.TURN_X1, self.TURN_Y1, self.z_current]],
            [[self.TURN_X0, self.TURN_Y0, self.z_current], [self.TURN_X0, self.TURN_Y0, self.z_current], [self.TURN_X1, self.TURN_Y1, self.z_current], [self.TURN_X1, self.TURN_Y1, self.z_current]],
            [[self.TURN_X0, self.TURN_Y0, self.Z_UP], [self.TURN_X0, self.TURN_Y0, self.z_current], [self.TURN_X1, self.TURN_Y1, self.z_current], [self.TURN_X1, self.TURN_Y1, self.z_current]],
            [[self.X_TURN, self.Y_START, self.Z_UP], [self.X_DEFAULT, self.Y_DEFAULT, self.z_current], [self.X_DEFAULT, self.Y_DEFAULT, self.z_current], [self.X_DEFAULT, self.Y_START, self.z_current]],
            [[self.X_DEFAULT, self.Y_START, self.z_current], [self.X_DEFAULT, self.Y_DEFAULT, self.z_current], [self.X_DEFAULT, self.Y_DEFAULT, self.z_current], [self.X_DEFAULT, self.Y_START, self.z_current]],
        ]

    MoveList.turn_right = turn_right_fixed
    print("[picrawler_fixes] Applied turn_right coordinate fix (TURN_X1/TURN_Y1 typo)")
