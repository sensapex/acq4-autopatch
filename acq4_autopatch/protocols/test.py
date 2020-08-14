import threading

import numpy as np
import scipy.stats
from acq4.util import Qt

from .patch_protocol import PatchProtocol


class ResultText(Qt.QPlainTextEdit):
    updateText = Qt.Signal()

    def __init__(self):
        Qt.QPlainTextEdit.__init__(self)
        self.records = []
        self.resetBtn = Qt.QPushButton("reset")
        self.resetBtn.setParent(self)
        self.resetBtn.resize(40, 15)
        self.resetBtn.clicked.connect(self.reset)
        self.updateText.connect(self._updateText)
        self.setWindowTitle("Stage/pipette accuracy test results")
        doc = self.document()
        font = doc.defaultFont()
        font.setFamily("Monospace")
        font.setStyleHint(font.TypeWriter)
        doc.setDefaultFont(font)
        self.resize(600, 600)

    def addRecord(self, rec):
        self.records.append(rec)
        self.updateText.emit()

    def _updateText(self):
        report = "\n\nPipette  X         Y         Z         XY        Stage\n"

        # per-target errors
        for rec in self.records:
            fields = {
                "stage": f"{np.linalg.norm(rec['stage']) * 1e6:0.2f}um",
                "pipettex": f"{rec['pipette'][0] * 1e6:0.2f}um",
                "pipettey": f"{rec['pipette'][1] * 1e6:0.2f}um",
                "pipettez": f"{rec['pipette'][2] * 1e6:0.2f}um",
                "pipettexy": f"{np.linalg.norm(rec['pipette'][:2]) * 1e6:0.2f}um",
            }
            report += "         {pipettex:10s}{pipettey:10s}{pipettez:10s}{pipettexy:10s}{stage:10s}\n".format(**fields)

        pip_err = np.array([rec["pipette"] for rec in self.records])
        stage_err = np.array([rec["stage"] for rec in self.records])

        # summary stats
        fields = {
            "stdx": f"{pip_err[:, 0].std() * 1e6:0.2f}um",
            "stdy": f"{pip_err[:, 1].std() * 1e6:0.2f}um",
            "stdz": f"{pip_err[:, 2].std() * 1e6:0.2f}um",
            "stdxy": f"{np.linalg.norm([pip_err[:, 0].std(), pip_err[:, 1].std()]) * 1e6:0.2f}um",
        }
        report += "Std      {stdx:10s}{stdy:10s}{stdz:10s}{stdxy:10s}\n".format(**fields)
        fields = {
            "meanx": f"{pip_err[:, 0].mean() * 1e6:0.2f}um",
            "meany": f"{pip_err[:, 1].mean() * 1e6:0.2f}um",
            "meanz": f"{pip_err[:, 2].mean() * 1e6:0.2f}um",
            "meanxy": f"{np.linalg.norm([pip_err[:, 0].mean(), pip_err[:, 1].mean()]) * 1e6:0.2f}um",
        }
        report += "Mean     {meanx:10s}{meany:10s}{meanz:10s}{meanxy:10s}\n".format(**fields)

        xydist = np.linalg.norm(pip_err[:, :2], axis=1)
        report += f"XY distance 95th percentile: {scipy.stats.scoreatpercentile(xydist, 95.0):0.2f}um"

        self.document().setPlainText(report)
        self.show()

    def reset(self):
        self.records = []
        self.document().setPlainText("")


resultText = ResultText()


class TestPatchProtocol(PatchProtocol):
    """Simplified patch protocol used for testing pipette / stage movement
    """

    name = "stage/manipulator test"

    def __init__(self, patchThread, patchAttempt):
        PatchProtocol.__init__(self, patchThread, patchAttempt)
        self.dev = patchThread.dev
        self.module = patchThread.module
        self.clickEvent = threading.Event()
        self.stageCameraLock = self.module.stageCameraLock
        self.camera = self.module.getCameraDevice()
        self.cameraMod = self.module.getCameraModule()
        self.lines = None

    def runPatchProtocol(self):
        # Grab click events fom the camera module while this protocol is running
        self.cameraMod.window().getView().scene().sigMouseClicked.connect(
            self.cameraModuleClicked, Qt.Qt.DirectConnection
        )
        try:
            self._runPatchProtocol()
        finally:
            self.cameraMod.window().getView().scene().sigMouseClicked.disconnect(self.cameraModuleClicked)

    def getClickPosition(self):
        self.clickEvent.clear()
        while True:
            if self.clickEvent.wait(0.2):
                break
            self.checkStop()
        return np.array(self.lastClick)

    def cameraModuleClicked(self, ev):
        cameraPos = self.camera.mapToGlobal([0, 0, 0])
        globalPos = self.cameraMod.window().getView().mapSceneToView(ev.scenePos())
        globalPos = [globalPos.x(), globalPos.y(), cameraPos[2]]
        self.lastClick = globalPos
        self.clickEvent.set()

    def _runPatchProtocol(self):
        pa = self.patchAttempt
        pa.setStatus("moving to target")

        # move to 100 um above current position
        pos = self.dev.pipetteDevice.globalPosition()
        pos[2] += 100e-6
        fut = self.dev.pipetteDevice._moveToGlobal(pos, "fast")
        self.wait([fut])

        # move to 100 um above target z value
        pos = pa.pipetteTargetPosition()
        pos[2] += 100e-6
        fut = self.dev.pipetteDevice._moveToGlobal(pos, "fast")
        self.wait([fut])

        self.dev.pipetteDevice.setTarget(pa.pipetteTargetPosition())

        # move to 10 um above cell
        pipPos = np.array(pa.pipetteTargetPosition()) + np.array([0, 0, 10e-6])
        # don't use target move here; we don't need all the obstacle avoidance.
        # fut = self.dev.pipetteDevice.goTarget(speed='fast')
        pfut = self.dev.pipetteDevice._moveToGlobal(pipPos, speed="slow")

        with self.stageCameraLock.acquire() as fut:
            pa.setStatus("Waiting for stage/camera")
            self.wait([fut], timeout=None)
            # Move to actual target, wait for click
            camPos = pa.globalTargetPosition()
            cfut = self.camera.moveCenterToGlobal(camPos, "fast")
            self.wait([pfut, cfut], timeout=None)

            pa.setStatus("Waiting click on target")
            targetClickPos = self.getClickPosition()
            stageErr = targetClickPos - camPos

            # Move to target + 10um, wait for click on pipette
            cfut = self.camera.moveCenterToGlobal(pipPos, "slow")
            self.wait([cfut], timeout=None)

            pa.setStatus("Waiting click on pipette")
            pipClickPos = self.getClickPosition()
            pipetteErr = pipClickPos - (targetClickPos + np.array([0, 0, 10e-6]))

            resultText.addRecord(
                {"pipette": pipetteErr, "stage": stageErr,}
            )
