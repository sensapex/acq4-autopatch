import json
import traceback
from collections import OrderedDict

import numpy as np
import pyqtgraph as pg
from acq4.util import Qt
from pyqtgraph import ptime


class PatchAttempt(Qt.QObject):
    """Stores 3D location, status, and results for a point to be patched.
    """

    status_changed = Qt.Signal(object, object)  # self, status
    new_event = Qt.Signal(object, object)  # self, event

    def __init__(self, pid, position, treeItem, targetItem):
        Qt.QObject.__init__(self)
        self.assigned_protocols = set()
        self.pid = pid
        self.position = position
        self.pipette_error = None
        self.tree_item = treeItem
        self.target_item = targetItem
        self.protocol = None
        self.pipette = None
        self.status = None
        self.result = {}
        self.error = None
        self.log = []
        self.log_file = None

    def reset(self):
        self.stop_logging()
        self.assigned_protocols = set()
        self.pipette = None
        self.pipette_error = None
        self.set_status("reset")
        self.result = {}
        self.error = None
        self.log = []
        self.status = None

    def has_started(self):
        return self.status is not None

    def set_protocol(self, prot):
        self.assigned_protocols.add(prot.name)
        self.protocol = prot

    def set_status(self, status):
        self.status = status
        self.log.append(
            OrderedDict(
                [
                    ("device", "None" if self.pipette is None else self.pipette.name()),
                    ("event_time", ptime.time()),
                    ("event", "statusChanged"),
                    ("status", status),
                ]
            )
        )
        self.status_changed.emit(self, status)

    def assign_pipette(self, pip):
        assert self.pipette in (None, pip), "Pipette can only be assigned once"
        self.pipette = pip
        self.set_status("assigned")

    def pipette_event(self, pip, event):
        self.log.append(event)
        self.write_log_event(event)
        self.new_event.emit(self, event)

    def set_log_file(self, fh):
        self.log_file = fh
        for ev in self.log:
            self.write_log_event(ev)

    def write_log_event(self, event):
        if self.log_file is None:
            return
        try:
            ev = json.dumps(event)
        except Exception:
            print(repr(ev))
            raise
        with open(self.log_file.name(), "a") as fh:
            fh.write(ev)
            fh.write("\n")

    def set_error(self, excinfo):
        self.error = excinfo
        exclass, exc, tb = excinfo
        self.set_status(f'error during "{self.status}" : {str(exc)}')
        ev = OrderedDict(
            [
                ("device", "None" if self.pipette is None else self.pipette.name()),
                ("event_time", ptime.time()),
                ("event", "error"),
                ("error", traceback.format_exception(*excinfo)),
            ]
        )
        self.pipette_event(self.pipette, ev)

    def pipette_target_position(self):
        """Return the global coordinate of the selected target for this patch attempt, corrected
        for the pipette position error.
        """
        pos = np.array(self.position)
        if self.pipette_error is not None:
            pos -= self.pipette_error
        return pos

    def global_target_position(self):
        """Return the global coordinate of the selected target for this patch attempt.
        """
        return np.array(self.position)

    def start_logging(self):
        """Connect device signals to begin logging events.
        """
        self.stop_logging()
        self.pipette.sigNewEvent.connect(self.pipette_event)

    def stop_logging(self):
        """Disconnect device signals to stop logging events.
        """
        if self.pipette is None:
            return
        pg.disconnect(self.pipette.sigNewEvent, self.pipette_event)

    def format_log(self):
        """Return a string describing all events logged for this attempt (for debugging)
        """
        log = [
            "========================================",
            f"       Patch attempt {self.pid:d}",
            f"       Current status: {self.status}",
            "========================================",
            "Event log:",
        ]
        for event in self.log:
            log.append("  ".join([f"{k}={v}" for k, v in event.items()]))
        if self.error is not None:
            log.append("========================================")
            log.append("Error:")
            log.extend(traceback.format_exception(*self.error))
        return "\n".join(log)
