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

    statusChanged = Qt.Signal(object, object)  # self, status
    newEvent = Qt.Signal(object, object)  # self, event

    def __init__(self, pid, position, treeItem, targetItem):
        Qt.QObject.__init__(self)
        self.assigned_protocols = set()
        self.pid = pid
        self.position = position
        self.pipetteError = None
        self.treeItem = treeItem
        self.targetItem = targetItem
        self.protocol = None
        self.pipette = None
        self.status = None
        self.result = {}
        self.error = None
        self.log = []
        self.logFile = None

    def reset(self):
        self.stopLogging()
        self.assigned_protocols = set()
        self.pipette = None
        self.pipetteError = None
        self.setStatus("reset")
        self.result = {}
        self.error = None
        self.log = []
        self.status = None

    def hasStarted(self):
        return self.status is not None

    def setProtocol(self, prot):
        self.assigned_protocols.add(prot.name)
        self.protocol = prot

    def setStatus(self, status):
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
        self.statusChanged.emit(self, status)

    def assignPipette(self, pip):
        assert self.pipette in (None, pip), "Pipette can only be assigned once"
        self.pipette = pip
        self.setStatus("assigned")

    def pipetteEvent(self, pip, event):
        self.log.append(event)
        self.writeLogEvent(event)
        self.newEvent.emit(self, event)

    def setLogFile(self, fh):
        self.logFile = fh
        for ev in self.log:
            self.writeLogEvent(ev)

    def writeLogEvent(self, event):
        if self.logFile is None:
            return
        try:
            ev = json.dumps(event)
        except Exception:
            print(repr(ev))
            raise
        with open(self.logFile.name(), "a") as fh:
            fh.write(ev)
            fh.write("\n")

    def setError(self, excinfo):
        self.error = excinfo
        exclass, exc, tb = excinfo
        self.setStatus(f'error during "{self.status}" : {str(exc)}')
        ev = OrderedDict(
            [
                ("device", "None" if self.pipette is None else self.pipette.name()),
                ("event_time", ptime.time()),
                ("event", "error"),
                ("error", traceback.format_exception(*excinfo)),
            ]
        )
        self.pipetteEvent(self.pipette, ev)

    def pipetteTargetPosition(self):
        """Return the global coordinate of the selected target for this patch attempt, corrected
        for the pipette position error.
        """
        pos = np.array(self.position)
        if self.pipetteError is not None:
            pos -= self.pipetteError
        return pos

    def globalTargetPosition(self):
        """Return the global coordinate of the selected target for this patch attempt.
        """
        return np.array(self.position)

    def startLogging(self):
        """Connect device signals to begin logging events.
        """
        self.stopLogging()
        self.pipette.sigNewEvent.connect(self.pipetteEvent)

    def stopLogging(self):
        """Disconnect device signals to stop logging events.
        """
        if self.pipette is None:
            return
        pg.disconnect(self.pipette.sigNewEvent, self.pipetteEvent)

    def formatLog(self):
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
