from __future__ import print_function, division

import os

import pyqtgraph as pg
from acq4.Manager import getManager
from acq4.modules.Module import Module
from acq4.util import Qt
from acq4.util.prioritylock import PriorityLock
from acq4.util.target import Target

from .job_queue import JobQueue
from .patch_attempt import PatchAttempt
from .patch_thread import PatchThread
from .protocols import allPatchProtocols

MainForm = Qt.importTemplate(".main_window")


class AutopatchModule(Module):
    moduleDisplayName = "Autopatch"
    moduleCategory = "Acquisition"

    def __init__(self, manager, name, config):
        # lock used to serialize access to shared stage/camera hardware
        self.stageCameraLock = PriorityLock()
        self._stageLockRequest = None

        self.patchAttempts = []
        self._cammod = None
        self._camdev = None
        self._nextPointID = 0
        self._plateCenter = config.get("plateCenter", (0, 0, 0))

        Module.__init__(self, manager, name, config)

        self.win = Qt.QWidget()
        self.win.resize(1600, 900)
        self.win.closeEvent = self.closeEvent
        self.ui = MainForm()
        self.ui.setupUi(self.win)

        for protocol in allPatchProtocols():
            self.ui.protocolCombo.addItem(protocol)

        for i, w in enumerate([40, 130, 100, 400]):
            self.ui.pointTree.header().resizeSection(i, w)

        # hard-code pipette name => status text box assignments
        # we'd have to rewrite this if we move beyond 4 pipettes or want to rename them..
        self.pipStatusText = {f"PatchPipette{i:d}": getattr(self.ui, f"pip{i:d}Status") for i in range(1, 5)}

        self.win.show()

        self.ui.addPointsBtn.toggled.connect(self.addPointsToggled)
        self.ui.removePointsBtn.clicked.connect(self.removePointsClicked)
        self.ui.startBtn.toggled.connect(self.startBtnToggled)
        self.ui.abortBtn.clicked.connect(self.abortClicked)
        self.ui.resetBtn.clicked.connect(self.resetClicked)
        self.ui.pointTree.itemSelectionChanged.connect(self.treeSelectionChanged)
        self.ui.protocolCombo.currentIndexChanged.connect(self.protocolComboChanged)
        self.ui.lockStageBtn.toggled.connect(self.lockStageBtnToggled)

        camMod = self.getCameraModule()

        pc = self.plateCenter()
        self.plateCenterLines = [
            pg.InfiniteLine(pos=pc[:2], angle=0, movable=False),
            pg.InfiniteLine(pos=pc[:2], angle=90, movable=False),
        ]
        for line in self.plateCenterLines:
            camMod.window().addItem(line)
        radius = 5e-3
        self.wellCircles = [
            Qt.QGraphicsEllipseItem(x - radius, y - radius, radius * 2, radius * 2) for x, y in config["wellPositions"]
        ]
        for wc in self.wellCircles:
            wc.setPen(pg.mkPen("y"))
            camMod.window().addItem(wc)

        cam = self.getCameraDevice()
        cam.sigGlobalTransformChanged.connect(self.cameraTransformChanged)

        # allow to disable safe move in config
        self.safeMoveEnabled = config.get("safeMove", True)

        self.jobQueue = JobQueue(config["patchDevices"], self)

        self.threads = []
        for pipName in config["patchDevices"]:
            pip = manager.getDevice(pipName)
            pip.setActive(True)

            # Write state config parameters to pipette state manager.
            # This does not play nicely with others; perhaps we should have our own state manager.
            stateConfig = pip.stateManager().stateConfig
            for k, v in config.get("patchStates", {}).items():
                stateConfig.setdefault(k, {})
                stateConfig[k].update(v)

            thread = PatchThread(pip, self)
            self.threads.append(thread)
            thread.start()

        self.loadConfig()
        self.protocolComboChanged()

    def window(self):
        return self.win

    def addPointsToggled(self):
        cammod = self.getCameraModule()
        if self.ui.addPointsBtn.isChecked():
            self.ui.startBtn.setChecked(False)
            cammod.window().getView().scene().sigMouseClicked.connect(self.cameraModuleClicked)
        else:
            Qt.disconnect(cammod.window().getView().scene().sigMouseClicked, self.cameraModuleClicked)

    def getCameraModule(self):
        if self._cammod is None:
            manager = getManager()
            mods = manager.listInterfaces("cameraModule")
            if len(mods) == 0:
                raise Exception("Open the Camera module first")
            self._cammod = manager.getModule(mods[0])
        return self._cammod

    def getCameraDevice(self):
        if self._camdev is None:
            manager = getManager()
            camName = self.config.get("imagingDevice", None)
            if camName is None:
                cams = manager.listInterfaces("camera")
                if len(cams) == 1:
                    camName = cams[0]
                else:
                    raise Exception(
                        f"Single camera device required (found {len(cams):d}) or 'imagingDevice' key in configuration."
                    )
            self._camdev = manager.getDevice(camName)
        return self._camdev

    def protocolComboChanged(self):
        prot = str(self.ui.protocolCombo.currentText())
        self.jobQueue.setProtocol(allPatchProtocols()[prot])

    def cameraModuleClicked(self, ev):
        if ev.button() != Qt.Qt.LeftButton:
            return

        camera = self.getCameraDevice()
        cameraPos = camera.mapToGlobal([0, 0, 0])

        globalPos = self._cammod.window().getView().mapSceneToView(ev.scenePos())
        globalPos = [globalPos.x(), globalPos.y(), cameraPos[2]]

        self.addPatchAttempt(globalPos)

    def addPatchAttempt(self, position):
        pid = self._nextPointID
        self._nextPointID += 1

        item = Qt.QTreeWidgetItem([str(pid), "", "", ""])
        self.ui.pointTree.addTopLevelItem(item)

        target = Target(movable=False)
        self._cammod.window().addItem(target)
        target.setPos(pg.Point(position[:2]))
        target.setDepth(position[2])
        target.setFocusDepth(position[2])
        target.circles = []
        for r in (3e-6, 5e-6):
            c = pg.QtGui.QGraphicsEllipseItem(0, 0, 1, 1)
            c.scale(r * 2, r * 2)
            c.setPos(-r, -r)
            c.setPen(pg.mkPen("b"))
            c.setParentItem(target)
            target.circles.append(c)

        pa = PatchAttempt(pid, position, item, target)
        item.patchAttempt = pa
        self.patchAttempts.append(pa)

        self.jobQueue.setJobs(self.patchAttempts)

        pa.statusChanged.connect(self.jobStatusChanged)

        return pa

    def selectedProtocol(self):
        return allPatchProtocols()[str(self.ui.protocolCombo.currentText())]

    def removePointsClicked(self):
        sel = self.ui.pointTree.selectedItems()
        for item in sel:
            self.removePatchAttempt(item.patchAttempt)

    def removePatchAttempt(self, pa):
        self.patchAttempts.remove(pa)

        index = self.ui.pointTree.indexOfTopLevelItem(pa.treeItem)
        self.ui.pointTree.takeTopLevelItem(index)

        pa.targetItem.scene().removeItem(pa.targetItem)

        self.jobQueue.setJobs(self.patchAttempts)

    def cameraTransformChanged(self):
        cam = self.getCameraDevice()
        fdepth = cam.mapToGlobal([0, 0, 0])[2]

        for pa in self.patchAttempts:
            pa.targetItem.setFocusDepth(fdepth)

    def startBtnToggled(self):
        if self.ui.startBtn.isChecked():
            self.ui.startBtn.setText("Stop")
            self.ui.addPointsBtn.setChecked(False)
            self.jobQueue.setJobs(self.patchAttempts)
            self.jobQueue.setEnabled(True)
        else:
            self.ui.startBtn.setText("Start")
            self.jobQueue.setEnabled(False)

    def abortClicked(self):
        """Stop all running jobs.
        """
        self.ui.startBtn.setChecked(False)
        for thread in self.threads:
            thread.stop()
            thread.wait()
            thread.start()

    def resetClicked(self):
        """Reset the state of all points so they can be run again.
        This is mostly meant for development to allow quick iteration.
        """
        for pa in self.patchAttempts:
            pa.reset()
        self.jobQueue.setJobs(self.patchAttempts)

    def closeEvent(self, ev):
        self.quit()
        return Qt.QWidget.closeEvent(self.win, ev)

    def quit(self):
        self.ui.startBtn.setChecked(False)
        self.ui.addPointsBtn.setChecked(False)
        for thread in self.threads:
            thread.stop()
        for pa in self.patchAttempts[:]:
            self.removePatchAttempt(pa)
        for item in self.plateCenterLines + self.wellCircles:
            scene = item.scene()
            if scene is not None:
                scene.removeItem(item)
        self.saveConfig()
        return Module.quit(self)

    def jobStatusChanged(self, job, status):
        item = job.treeItem
        pip = job.pipette.name() if job.pipette is not None else ""
        item.setText(1, "" if job.protocol is None else job.protocol.name)
        item.setText(2, pip)
        item.setText(3, status)
        pipnum = pip[12:] if pip.lower().startswith("patchpipette") else pip
        statusTxt = self.pipStatusText.get(pip)
        if statusTxt is not None:
            statusTxt.setText(f"{pipnum}: {status}")

    def deviceStatusChanged(self, device, status):
        # todo: implement per-pipette UI
        print(f"Device status: {device}, {status}")

    def treeSelectionChanged(self):
        sel = self.ui.pointTree.selectedItems()
        if len(sel) == 1:
            # TODO: something more user-friendly; this is just for development
            log = sel[0].patchAttempt.formatLog()
            self.ui.resultText.setPlainText(log)

    def plateCenter(self):
        return self._plateCenter

    def saveConfig(self):
        geom = self.win.geometry()
        config = {
            # 'plateCenter': list(self._plateCenter),
            # 'window': str(self.win.saveState().toPercentEncoding()),
            "geometry": [geom.x(), geom.y(), geom.width(), geom.height()],
        }
        configfile = os.path.join("modules", self.name + ".cfg")
        man = getManager()
        man.writeConfigFile(config, configfile)

    def loadConfig(self):
        configfile = os.path.join("modules", self.name + ".cfg")
        man = getManager()
        config = man.readConfigFile(configfile)
        if "geometry" in config:
            geom = Qt.QRect(*config["geometry"])
            self.win.setGeometry(geom)
        # if 'window' in config:
        #     ws = Qt.QByteArray.fromPercentEncoding(config['window'])
        #     self.win.restoreState(ws)
        # if 'plateCenter' in config:
        #     self.setPlateCenter(config['plateCenter'])

    def lockStageBtnToggled(self, v):
        if self._stageLockRequest is not None:
            self._stageLockRequest.release()
            self._stageLockRequest.sigFinished.disconnect(self.stageLockAcquired)
            self._stageLockRequest = None

        if v is True:
            # acquire stage lock with higher priority than patch threads
            self._stageLockRequest = self.stageCameraLock.acquire(priority=10)
            self._stageLockRequest.sigFinished.connect(self.stageLockAcquired)
            self.ui.lockStageBtn.setText("Locking stage...")
        else:
            self.ui.lockStageBtn.setText("Lock stage")

    def stageLockAcquired(self, req):
        self.ui.lockStageBtn.setText("Stage locked!")
