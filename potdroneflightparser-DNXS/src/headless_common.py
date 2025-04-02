# Functions commonly used in the app
# Based on common.py by Koen Aerts

class Common:
    def __init__(self, parent=None):
        self.parent = parent
        self.use_metric = True  # Default to metric units

    def dist_val(self, num):
        """Return specified distance in the proper Unit (metric vs imperial)."""
        if num is None:
            return None
        return num * 3.28084 if not self.use_metric else num

    def shorten_dist_val(self, numval):
        """Convert ft to miles or m to km."""
        if numval is None:
            return ""
        num = float(numval) if isinstance(numval, str) else numval
        return self.fmt_num(num / 5280.0, True) if not self.use_metric else self.fmt_num(num / 1000.0, True)

    def dist_unit(self):
        """Return selected distance unit of measure."""
        return "ft" if not self.use_metric else "m"

    def dist_unit_km(self):
        """Return selected distance unit of measure."""
        return "mi" if not self.use_metric else "km"

    def fmt_num(self, num, decimal=False):
        """Format number."""
        if num is None:
            return ""
        return f"{num:.0f}" if not decimal else f"{num:.2f}"

    def speed_val(self, num):
        """Return specified speed in the proper Unit (metric vs imperial).
        For metric, keep it in m/s (no conversion).
        For imperial, convert to mph."""
        if num is None:
            return None
        return num * 2.236936 if not self.use_metric else num  # Keep as m/s for metric

    def speed_unit(self):
        """Return selected speed unit of measure."""
        return "mph" if not self.use_metric else "m/s"  # Changed from "kph" to "m/s"
