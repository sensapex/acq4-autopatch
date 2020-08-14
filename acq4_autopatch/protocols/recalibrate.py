import threading
import time

import numpy as np
import pyqtgraph as pg
from acq4.util import Qt
from acq4.util.threadrun import runInGuiThread

from .patch_protocol import PatchProtocol


class RecalibrateProtocol(PatchProtocol):
    """Base class for protocols that visit each target +10um and measure the pipette calibration error 
    """

    name = None

    def __init__(self, patchThread, patchAttempt):
        PatchProtocol.__init__(self, patchThread, patchAttempt)
        self.dev = patchThread.dev
        self.module = patchThread.module
        self.clickEvent = threading.Event()
        self.stageCameraLock = self.module.stageCameraLock
        self.camera = self.module.getCameraDevice()
        self.cameraMod = self.module.getCameraModule()

    def runPatchProtocol(self):
        # How far above target to run calibration?
        #  - low values (10 um) potentially have worse machine vision performance due to being very close to cells
        #  - high values (100 um) potentially yield a bad correction due to errors that accumulate over the large distance to the cell
        calibrationHeight = 30e-6

        pa = self.patchAttempt
        if not hasattr(pa, "originalPosition"):
            pa.originalPosition = np.array(pa.position)

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

        # set pipette target position
        self.dev.pipetteDevice.setTarget(pa.pipetteTargetPosition())

        # move pipette to 10 um above corrected target
        pipPos = pa.pipetteTargetPosition() + np.array([0, 0, calibrationHeight])
        # don't use target move here; we don't need all the obstacle avoidance.
        # fut = self.dev.pipetteDevice.goTarget(speed='fast')
        pfut = self.dev.pipetteDevice._moveToGlobal(pipPos, speed="slow")

        with self.stageCameraLock.acquire() as fut:
            pa.setStatus("Waiting for stage/camera")
            self.wait([fut], timeout=None)

            # move stage/focus above actual target
            camPos = pa.globalTargetPosition() + np.array([0, 0, calibrationHeight])
            cfut = self.camera.moveCenterToGlobal(camPos, "fast")
            self.wait([pfut, cfut], timeout=None)

            # Offset from target to where pipette actually landed
            try:
                self.patchAttempt.pipetteError = self.getPipetteError()
            except RuntimeError:
                self.patchAttempt.pipetteError = np.array([np.nan] * 3)
                raise

    def getPipetteError(self):
        """Return the calibration offset between the expected pipette position and the known pipette position
        """
        raise NotImplementedError()


class AutoRecalibrateProtocol(RecalibrateProtocol):
    name = "auto recalibrate"

    def __init__(self, *args, **kwds):
        RecalibrateProtocol.__init__(self, *args, **kwds)
        self.line = None

    def getPipetteError(self):
        """Return error vector that should be added to pipette position fotr the current target.

        Error vector may contain NaN to indicate that the correction failed and this target should not be attempted.
        """
        pa = self.patchAttempt
        pa.setStatus("Measuring pipette error")

        perfVals = []
        pipetteDiffVals = []
        targetErrVals = []
        focusErrVals = []

        targetPos = np.array(pa.pipetteTargetPosition())

        # Make a few attempts to optimize pipette position. Iterate until
        #  - z is in focus on the pipette tip
        #  - pipette x,y is over the target
        for i in range(4):
            cameraPos = self.camera.globalCenterPosition("roi")

            # pipette position according to manipulator
            reportedPos = np.array(self.dev.pipetteDevice.globalPosition())

            # estimate tip position measured by machine vision
            measuredPos, perf = self.dev.pipetteDevice.tracker.measureTipPosition(threshold=0.4, movePipette=False)
            measuredPos = np.array(measuredPos)

            # generate some error metrics:
            # how far is the pipette from its reported position
            pipetteDiff = measuredPos - reportedPos
            # how far in Z is the pipette from the focal plane
            focusError = abs(measuredPos[2] - cameraPos[2])
            # how far in XY is the pipette from the target
            targetDiff = targetPos[:2] - measuredPos[:2]
            targetError = np.linalg.norm(targetDiff)

            # track performance so we can decide later whether to abandon this point
            perfVals.append(perf)
            pipetteDiffVals.append(pipetteDiff)
            focusErrVals.append(focusError)
            targetErrVals.append(targetError)

            # show the error line and pause briefly (just for debugging; we could remove this to speed up the process)
            self.showErrorLine(reportedPos, measuredPos)

            futs = []
            if focusError > 3e-6:
                # refocus on pipette tip (don't move pipette in z because if error prediction is wrong, we could crash)
                cameraPos[2] = measuredPos[2]
                futs.append(self.camera.moveCenterToGlobal(cameraPos, "slow"))

            if targetError > 1.5e-6:
                # reposition pipette x,y closer to target
                ppos = reportedPos.copy()
                ppos[:2] += targetDiff
                futs.append(self.dev.pipetteDevice._moveToGlobal(ppos, "slow"))

            if len(futs) > 0:
                # wait for requested moves to complete and try again
                self.wait(futs)
                time.sleep(0.3)  # wait for positions to catch up.. we can remove this after bug fixed!
                pa.setStatus(f"Measuring pipette error: adjust and iterate  ({i:d})")
            else:
                # no moves needed this round; we are done.
                break

        # Now decide whether to pass or fail this calibration.
        if focusErrVals[-1] > 3e-6 or targetErrVals[-1] > 3e-6 or perfVals[-1] < 0.5:
            raise RuntimeError(
                f"Measuring pipette error: failed  (focus error: {focusErrVals}  target error: {targetErrVals}  correlation: {perfVals})"
            )

        pa.setStatus(f"Measuring pipette error: success {pipetteDiff}")
        return pipetteDiff

    def showErrorLine(self, pt1, pt2):
        runInGuiThread(self._showErrorLine, pt1, pt2)
        time.sleep(1.5)
        runInGuiThread(self._removeErrorLine)

    def _showErrorLine(self, pt1, pt2):
        self._removeErrorLine()
        self.line = pg.QtGui.QGraphicsLineItem(pt1[0], pt1[1], pt2[0], pt2[1])
        self.line.setPen(pg.mkPen("r"))
        self.cameraMod.window().addItem(self.line)

    def _removeErrorLine(self):
        if self.line is None:
            return
        self.line.scene().removeItem(self.line)
        self.line = None


class ManualRecalibrateProtocol(RecalibrateProtocol):
    name = "manual recalibrate"

    def __init__(self, patchThread, patchAttempt):
        RecalibrateProtocol.__init__(self, patchThread, patchAttempt)

    def runPatchProtocol(self):
        # Grab click events fom the camera module while this protocol is running
        self.cameraMod.window().getView().scene().sigMouseClicked.connect(
            self.cameraModuleClicked, Qt.Qt.DirectConnection
        )
        try:
            RecalibrateProtocol.runPatchProtocol(self)
        finally:
            self.cameraMod.window().getView().scene().sigMouseClicked.disconnect(self.cameraModuleClicked)

    def getPipetteError(self):
        pa = self.patchAttempt
        pa.setStatus("Waiting for user click")
        clickPos = self.getClickPosition()
        pos = np.array(self.dev.pipetteDevice.globalPosition())
        return clickPos - pos

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
