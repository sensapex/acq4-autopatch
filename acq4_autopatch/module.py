from __future__ import print_function, division

import os
import numpy as np

import pyqtgraph as pg
from acq4.Manager import getManager
from acq4.modules.Module import Module
from acq4.util import Qt
from acq4.util.prioritylock import PriorityLock
from acq4.util.target import Target

from .job_queue import JobQueue
from .patch_attempt import PatchAttempt
from .patch_thread import PatchThread
from .protocols import all_patch_protocols

MainForm = Qt.importTemplate(".main_window")


def _calculate_pipette_boundaries(patch_devices):
    pipettes = [pp.pipetteDevice for pp in patch_devices]
    homes = np.array([pip.parentDevice().homePosition()[:2] for pip in pipettes])
    if len(homes) == 2:
        # boundaries are symmetric
        midpoint = np.mean((homes[0], homes[1]), axis=0)
        opposite = -1 * midpoint
        return {
            pipettes[0]: (midpoint, opposite),
            pipettes[1]: (opposite, midpoint),
        }
    ordered_indexes, ordered_homes = zip(
        *sorted(enumerate(homes), key=lambda val: np.arctan2(val[1][1], val[1][0]))
    )

    def boundaries_for_index(i: int):
        return (
            np.mean((ordered_homes[i], ordered_homes[(i + 1) % len(homes)]), axis=0),
            np.mean((ordered_homes[i], ordered_homes[(i - 1) % len(homes)]), axis=0),
        )

    return {pipettes[orig_i]: boundaries_for_index(i) for i, orig_i in enumerate(ordered_indexes)}


class AutopatchModule(Module):
    """
    Config
    ----------

    imagingDevice : str
        Usually "Camera".
    patchDevices : dict
        The patch pipette device names and their locations. E.g.::
            PatchPipette1: (0, 0)  # bottom-left quad
            PatchPipette2: (50*mm, 0)  # bottom-right quad
    plateCenter : tuple
        Global 3d coordinates for the center of the plate. E.g. (0, 0, 0)
    wellPositions : list(tuple)
        Global 2d coordinates of the wells. E.g. [(0, 0), (50*mm, 0)]
    patchStates : dict
        For each patch state, overrides for config options. See
        acq4/devices/PatchPipette/states.py in the ACQ4 source code for the
        full list of those. E.g.::
            seal:
                autoSealTimeout: 60
                pressureMode: 'auto'
            cell attached:
                autoBreakInDelay: 5.0
    """
    moduleDisplayName = "Autopatch"
    moduleCategory = "Acquisition"

    def __init__(self, manager, name, config):
        # lock used to serialize access to shared stage/camera hardware
        self.stage_camera_lock = PriorityLock()
        self._stage_lock_request = None

        self.patch_attempts = []
        self._cammod = None
        self._camdev = None
        self._next_point_id = 0
        self.plate_center = config.get("plateCenter", (0, 0, 0))

        Module.__init__(self, manager, name, config)

        self.win = Qt.QWidget()
        self.win.resize(1600, 900)
        self.win.closeEvent = self.close_event
        self.ui = MainForm()
        self.ui.setupUi(self.win)

        for protocol in all_patch_protocols():
            self.ui.protocolCombo.addItem(protocol)

        for i, w in enumerate([40, 130, 100, 400]):
            self.ui.pointTree.header().resizeSection(i, w)

        # hard-code pipette name => status text box assignments
        # we'd have to rewrite this if we move beyond 4 pipettes or want to rename them..
        self.pip_status_text = {f"PatchPipette{i:d}": getattr(self.ui, f"pip{i:d}Status") for i in range(1, 5)}

        self.win.show()

        self.ui.addPointsBtn.toggled.connect(self.add_points_toggled)
        self.ui.removePointsBtn.clicked.connect(self.remove_points_clicked)
        self.ui.startBtn.toggled.connect(self.start_btn_toggled)
        self.ui.abortBtn.clicked.connect(self.abort_clicked)
        self.ui.resetBtn.clicked.connect(self.reset_clicked)
        self.ui.pointTree.itemSelectionChanged.connect(self.tree_selection_changed)
        self.ui.protocolCombo.currentIndexChanged.connect(self.protocol_combo_changed)
        self.ui.lockStageBtn.toggled.connect(self.lock_stage_btn_toggled)

        cam_mod = self.get_camera_module()

        self.plate_center_lines = [
            pg.InfiniteLine(pos=self.plate_center[:2], angle=0, movable=False),
            pg.InfiniteLine(pos=self.plate_center[:2], angle=90, movable=False),
        ]
        for line in self.plate_center_lines:
            cam_mod.window().addItem(line)
        radius = 5e-3
        self.well_circles = [
            Qt.QGraphicsEllipseItem(x - radius, y - radius, radius * 2, radius * 2) for x, y in config["wellPositions"]
        ]
        for wc in self.well_circles:
            wc.setPen(pg.mkPen("y"))
            cam_mod.window().addItem(wc)

        cam = self.get_camera_device()
        cam.sigGlobalTransformChanged.connect(self.camera_transform_changed)

        self.job_queue = JobQueue(config["patchDevices"], self)

        self.threads = []
        man = getManager()
        patch_devices = [man.getDevice(pipName) for pipName in config["patchDevices"]]
        self.boundaries_by_pipette = _calculate_pipette_boundaries(patch_devices)
        for pip in patch_devices:
            pip.setActive(True)

            # Write state config parameters to pipette state manager.
            # This does not play nicely with others; perhaps we should have our own state manager.
            state_config = pip.stateManager().stateConfig
            for k, v in config.get("patchStates", {}).items():
                state_config.setdefault(k, {})
                state_config[k].update(v)

            thread = PatchThread(pip, self)
            self.threads.append(thread)
            thread.start()

        self.load_config()
        self.protocol_combo_changed()

    def window(self):
        return self.win

    def add_points_toggled(self):
        cammod = self.get_camera_module()
        if self.ui.addPointsBtn.isChecked():
            self.ui.startBtn.setChecked(False)
            cammod.window().getView().scene().sigMouseClicked.connect(self.camera_module_clicked)
        else:
            Qt.disconnect(cammod.window().getView().scene().sigMouseClicked, self.camera_module_clicked)

    def get_camera_module(self):
        if self._cammod is None:
            manager = getManager()
            mods = manager.listInterfaces("cameraModule")
            if len(mods) == 0:
                raise Exception("Open the Camera module first")
            self._cammod = manager.getModule(mods[0])
        return self._cammod

    def get_camera_device(self):
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

    def protocol_combo_changed(self):
        prot = str(self.ui.protocolCombo.currentText())
        self.job_queue.set_protocol(all_patch_protocols()[prot])

    def camera_module_clicked(self, ev):
        if ev.button() != Qt.Qt.LeftButton:
            return

        camera = self.get_camera_device()
        cameraPos = camera.mapToGlobal([0, 0, 0])

        globalPos = self._cammod.window().getView().mapSceneToView(ev.scenePos())
        globalPos = [globalPos.x(), globalPos.y(), cameraPos[2]]

        self.add_patch_attempt(globalPos)

    def add_patch_attempt(self, position):
        pid = self._next_point_id
        self._next_point_id += 1

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
        self.patch_attempts.append(pa)

        self.job_queue.set_jobs(self.patch_attempts)

        pa.status_changed.connect(self.job_status_changed)

        return pa

    def selected_protocol(self):
        return all_patch_protocols()[str(self.ui.protocolCombo.currentText())]

    def remove_points_clicked(self):
        sel = self.ui.pointTree.selectedItems()
        for item in sel:
            self.remove_patch_attempt(item.patchAttempt)

    def remove_patch_attempt(self, pa):
        self.patch_attempts.remove(pa)

        index = self.ui.pointTree.indexOfTopLevelItem(pa.tree_item)
        self.ui.pointTree.takeTopLevelItem(index)

        pa.target_item.scene().removeItem(pa.target_item)

        self.job_queue.set_jobs(self.patch_attempts)

    def camera_transform_changed(self):
        cam = self.get_camera_device()
        fdepth = cam.mapToGlobal([0, 0, 0])[2]

        for pa in self.patch_attempts:
            pa.target_item.setFocusDepth(fdepth)

    def start_btn_toggled(self):
        if self.ui.startBtn.isChecked():
            self.ui.startBtn.setText("Stop")
            self.ui.addPointsBtn.setChecked(False)
            self.job_queue.set_jobs(self.patch_attempts)
            self.job_queue.set_enabled(True)
        else:
            self.ui.startBtn.setText("Start")
            self.job_queue.set_enabled(False)

    def abort_clicked(self):
        """Stop all running jobs.
        """
        self.ui.startBtn.setChecked(False)
        for thread in self.threads:
            thread.stop()
            thread.wait()
            thread.start()

    def reset_clicked(self):
        """Reset the state of all points so they can be run again.
        This is mostly meant for development to allow quick iteration.
        """
        for pa in self.patch_attempts:
            pa.reset()
        self.job_queue.set_jobs(self.patch_attempts)

    def close_event(self, ev):
        self.quit()
        return Qt.QWidget.close_event(self.win, ev)

    def quit(self):
        self.ui.startBtn.setChecked(False)
        self.ui.addPointsBtn.setChecked(False)
        for thread in self.threads:
            thread.stop()
        for pa in self.patch_attempts[:]:
            self.remove_patch_attempt(pa)
        for item in self.plate_center_lines + self.well_circles:
            scene = item.scene()
            if scene is not None:
                scene.removeItem(item)
        self.save_config()
        return Module.quit(self)

    def job_status_changed(self, job, status):
        item = job.tree_item
        pip = job.pipette.name() if job.pipette is not None else ""
        item.setText(1, "" if job.protocol is None else job.protocol.name)
        item.setText(2, pip)
        item.setText(3, status)
        pipnum = pip[12:] if pip.lower().startswith("patchpipette") else pip
        statusTxt = self.pip_status_text.get(pip)
        if statusTxt is not None:
            statusTxt.setText(f"{pipnum}: {status}")

    def device_status_changed(self, device, status):
        # todo: implement per-pipette UI
        print(f"Device status: {device}, {status}")

    def tree_selection_changed(self):
        sel = self.ui.pointTree.selectedItems()
        if len(sel) == 1:
            # TODO: something more user-friendly; this is just for development
            log = sel[0].patchAttempt.format_log()
            self.ui.resultText.setPlainText(log)

    def save_config(self):
        geom = self.win.geometry()
        config = {
            # 'plateCenter': list(self._plateCenter),
            # 'window': str(self.win.saveState().toPercentEncoding()),
            "geometry": [geom.x(), geom.y(), geom.width(), geom.height()],
        }
        configfile = os.path.join("modules", self.name + ".cfg")
        man = getManager()
        man.writeConfigFile(config, configfile)

    def load_config(self):
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

    def lock_stage_btn_toggled(self, v):
        if self._stage_lock_request is not None:
            self._stage_lock_request.release()
            self._stage_lock_request.sigFinished.disconnect(self.stage_lock_acquired)
            self._stage_lock_request = None

        if v is True:
            # acquire stage lock with higher priority than patch threads
            self._stage_lock_request = self.stage_camera_lock.acquire(priority=10)
            self._stage_lock_request.sigFinished.connect(self.stage_lock_acquired)
            self.ui.lockStageBtn.setText("Locking stage...")
        else:
            self.ui.lockStageBtn.setText("Lock stage")

    def stage_lock_acquired(self, req):
        self.ui.lockStageBtn.setText("Stage locked!")
