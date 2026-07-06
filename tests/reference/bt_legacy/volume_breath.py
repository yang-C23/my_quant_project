from __future__ import annotations

import backtrader as bt


class VolumeBreath(bt.Indicator):
    lines = ("avghigh", "avglow", "activity")
    params = (
        ("window", 30),
        ("ratio", 3.5),
    )

    def __init__(self):
        self.addminperiod(self.p.window)

    def next(self):
        vols = list(self.data.volume.get(size=self.p.window))
        vols = [float(v) for v in vols if v is not None]
        if len(vols) < 3:
            self.lines.avghigh[0] = 0.0
            self.lines.avglow[0] = 0.0
            self.lines.activity[0] = 0.0
            return

        sorted_vols = sorted(vols)
        low3 = sorted_vols[:3]
        high3 = sorted_vols[-3:]

        avghigh = sum(high3) / 3.0
        avglow = sum(low3) / 3.0

        self.lines.avghigh[0] = avghigh
        self.lines.avglow[0] = avglow
        self.lines.activity[0] = 1.0 if avglow > 0 and avghigh > self.p.ratio * avglow else 0.0
