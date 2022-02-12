import numpy as np
import sys
import time

from acq4.Manager import getManager
from acq4.util import Qt
from acq4.util.threadrun import runInGuiThread
from .patch_protocol import PatchProtocol
try:
    import queue
except ImportError:
    import Queue as queue


class TaskRunnerPatchProtocol(PatchProtocol):
    """Patch protocol implementing:

    - Move to cell, take brightfield photo, autopatch 
    - Initiate TaskRunner protocol
    - Clean pipette
    - Move pipette home and request swap (if broken / clogged)
    """

    name = "task runner"

    def __init__(self, patchThread, patchAttempt):
        PatchProtocol.__init__(self, patchThread, patchAttempt)
        self.dev = patchThread.dev
        self.module = patchThread.module
        self.stageCameraLock = self.module.stage_camera_lock
        self.camera = self.module.get_camera_device()
        self.scope = self.camera.getScopeDevice()

        man = getManager()
        self.dh = man.getCurrentDir().mkdir(f"patch_attempt_{self.patchAttempt.pid:04d}", autoIncrement=True)
        patchAttempt.set_log_file(self.dh["patch.log"])

        self.stateQueue = queue.Queue()
        # this code is running in a thread, so it is necessary to specify that
        # the signal must be delivered in the main thread (since we are not running an event loop)
        self.dev.stateManager().sigStateChanged.connect(self.devStateChanged, Qt.Qt.DirectConnection)

    def devStateChanged(self, stateManager, state):
        self.stateQueue.put(state)

    def runPatchProtocol(self):
        pa = self.patchAttempt

        if not self.dev.isTipClean():
            self.cleanPipette()

        try:
            self.dev.setState("bath")
            time.sleep(5)

            self.patchCell()

            finalState = self.dev.getState()
            if finalState.stateName != "whole cell":
                raise Exception(f"Failed to reach whole cell state (ended at {finalState}).")

            with self.stageCameraLock.acquire() as fut:
                pa.set_status("Waiting for stage/camera")
                self.wait([fut], timeout=None)
                self.configureCamera()
                self.runProtocol(pa)

        except:
            pa.set_error(sys.exc_info())
        finally:
            if self.dev.broken:
                self.swapPipette()
            elif not self.dev.clean:
                self.cleanPipette()

    def patchCell(self):
        pa = self.patchAttempt

        # Set target cell position, taking error correction into account
        targetPos = pa.pipette_target_position()
        if not np.all(np.isfinite(targetPos)):
            raise Exception("No valid target position for this attempt (probably automatic recalibration failed)")

        pa.set_status("moving to target")
        self.dev.pipetteDevice.setTarget(targetPos)

        # move to 100 um above cell, fast
        pos = np.array(targetPos) + np.array([100e-6, 100e-6, 100e-6])
        fut = self.dev.pipetteDevice._moveToGlobal(pos, speed="fast")
        self.wait([fut])

        # move to 10 um above cell, slow
        pos = np.array(targetPos) + np.array([0, 0, 10e-6])
        # don't use target move here; we don't need all the obstacle avoidance.
        # fut = self.dev.pipetteDevice.goTarget(speed='fast')
        fut = self.dev.pipetteDevice._moveToGlobal(pos, speed="slow")
        self.wait([fut])

        self.clearStateQueue()

        # kick off cell detection; wait until patched or failed
        pa.set_status("cell patching")
        self.dev.setState("cell detect")
        while True:
            self.checkStop()
            try:
                state = self.stateQueue.get(timeout=0.2)
            except queue.Empty:
                continue

            if state.stateName in ("whole cell", "fouled", "broken"):
                return
            else:
                pa.set_status(f"cell patching: {state.stateName}")

            while True:
                try:
                    # raise exception if this state fails
                    state.wait(timeout=0.2)
                    break
                except state.Timeout:
                    self.checkStop()

    def abortPatchProtocol(self):
        pass

    def clearStateQueue(self):
        # clear out information about any pipette states before now
        while not self.stateQueue.empty():
            self.stateQueue.get(timeout=0)

    def runProtocol(self, pa):
        """Cell is patched; lock the stage and begin protocol.
        """
        # focus camera on cell
        pa.set_status("focus on cell")
        self.camera.moveCenterToGlobal(pa.global_target_position(), speed="fast", center="roi").wait()

        man = getManager()
        turret = man.getDevice("FilterTurret")
        t_lamp = man.getDevice("Illumination")
        rl_shutter = man.getDevice("ReflectiveLightShutter")

        # set filter wheel / illumination
        turret.setPosition(1).wait()
        time.sleep(2)  # force bright field for good picture
        t_lamp.setActive(True)
        rl_shutter.setIsOpen(False)

        # take a picture
        pa.set_status("say cheese!")
        frame = self.camera.acquireFrames(n=1, stack=False)
        frame.saveImage(self.dh, "patch_image.tif")

        pa.set_status("running whole cell protocol")

        # switch to RL
        turret.setPosition(0).wait()
        time.sleep(2)  # turn off bright field
        t_lamp.setActive(False)
        rl_shutter.setIsOpen(True)
        time.sleep(1)

        cameraParams = self.camera.getParams()
        try:
            # take another picture
            self.camera.setParams({"exposure": 0.05, "binning": (4, 4)})

            frame = self.camera.acquireFrames(n=1, stack=False)
            frame.saveImage(self.dh, "fluor_image.tif")

            man = getManager()
            # TODO: select correct task runner for this pipette
            taskrunner = None
            for mod in man.listModules():
                if not mod.startswith("Task Runner"):
                    continue
                mod = man.getModule(mod)
                if self.dev.clampDevice.name() in mod.docks:
                    taskrunner = mod
                    break

            assert taskrunner is not None, f"No task runner found that uses {self.dev.clampDevice.name()}"

            # 300 Hz
            # self.camera.setParams({'regionH': 700, 'regionY': 680, 'regionX': 8, 'regionW': 2028, 'exposure': 0.0030013})
            # 1kHz
            self.camera.setParams(
                {
                    "regionH": 164,
                    "regionY": 940,
                    "regionX": 8,
                    "regionW": 2032,
                    "exposure": 0.0010134,
                    "binning": (4, 4),
                }
            )

            # prepare camera to be triggered by the DAQ for this pipette
            self.configureCamera()
            fut = runInGuiThread(taskrunner.runSequence, store=True, storeDirHandle=self.dh)
            try:
                self.wait([fut], timeout=300)
            except self.patchThread.Stopped:
                fut.stop()
                raise

        finally:
            # switch off RL
            turret.setPosition(1).wait()
            time.sleep(2)  # scope automatically changes RL/TL settings, sometimes in a bad way. sleep and set manually:
            t_lamp.SetTLIllumination(1)
            t_lamp.SetRLIllumination(1)

            self.camera.setParams(cameraParams)  # , autoRestart=True, autoCorrect=True)

            pa.set_status("restart acquire video of camera")
            self.camera.start()

        time.sleep(2)
        pa.set_status("whole cell protocol complete")

    def configureCamera(self):
        """Set camera exposure/trigger channels for this pipette's DAQ.
        """
        # note: we'd love it if the camera and DAQ could just automatically decide which trigger
        # channels to use, but that's not supported yet so this is a temporary workaround.
        if "cameraChannels" in self.module.config:
            exp, trig = self.module.config["cameraChannels"][self.dev.name()]
            self.camera.reconfigureChannel("exposure", {"channel": exp})
            self.camera.reconfigureChannel("trigger", {"channel": trig})

    def cleanPipette(self):
        pa = self.patchAttempt
        pa.set_status("cleaning pipette")
        self.clearStateQueue()
        fut = self.dev.setState("clean")

        # wait for cleaning to finish
        self.wait([fut], timeout=120)

    def swapPipette(self):
        pa = self.patchAttempt
        pa.set_status("requesting new pipette")
        self.dev.setState("out")
        self.dev.goHome("fast")
        self.dev.requestNewPipette()
