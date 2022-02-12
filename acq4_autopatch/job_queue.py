import numpy as np

from acq4.devices.PatchPipette import PatchPipette
from acq4.util.Mutex import Mutex
from acq4_autopatch.patch_attempt import PatchAttempt


class JobQueue(object):
    """Stores a list of jobs and assigns them by request.

    Pipettes are selected for each job based on the quadrant that the target appears in.
    """

    def __init__(self, module):
        self.module = module
        self.protocol = None
        self.job_strategies = {
            "Closest First": request_job_closest_first,
            "Fair (using chambers)": request_job_fair_using_recording_chambers,
            # needs more testing
            # "Fair (using geometry)": request_job_fair_geometric,
        }
        self.current_strategy_name = "Fair (using chambers)"
        self.all_jobs = []
        self.queued_jobs = []
        self.center = module.plate_center
        self.enabled = False
        self.positions = np.empty((0, 3))
        self.lock = Mutex(recursive=True)

    def set_protocol(self, prot):
        self.protocol = prot
        self.set_jobs(self.all_jobs)

    def set_enabled(self, en):
        """If enabled, then requestJob() will attempt to return the next available job.
        If disabled, then requestJob() will return None.
        """
        self.enabled = en

    def set_jobs(self, jobs):
        with self.lock:
            # queue up all jobs that have not run this protocol yet
            self.all_jobs = jobs
            self.queued_jobs = [j for j in jobs if self.protocol.name not in j.assigned_protocols]

    def add_job_strategy(self, name, func):
        self.job_strategies[name] = func

    def set_job_distribution_strategy(self, strategy_name):
        self.current_strategy_name = strategy_name

    def request_job(self, patch_pipette):
        return self.job_strategies[self.current_strategy_name](self, patch_pipette)


def _can_anybody_reach_job(autopatch, job: PatchAttempt):
    for pp in autopatch.get_patch_devices():
        for well in pp.pipetteDevice.getRecordingChambers():
            if well.containsPoint(job.position):
                return True
    return False


def request_job_closest_first(job_queue, patch_pipette: PatchPipette):
    with job_queue.lock:
        if not job_queue.enabled:
            return None

        if any(j.has_started() and not j.is_done for j in job_queue.all_jobs):
            return None

        reachable_jobs = [
            (i, job) for i, job in enumerate(job_queue.queued_jobs)
            if _can_anybody_reach_job(job_queue.module, job)
        ]
        if len(reachable_jobs) == 0:
            return None

        positions = np.array([job.position[:2] for i, job in reachable_jobs])
        camera = patch_pipette.imagingDevice()
        dist_to_camera = np.linalg.norm(positions - camera.globalCenterPosition()[:2], axis=1)
        next_idx, next_job = reachable_jobs[np.argmin(dist_to_camera)]
        for well in patch_pipette.pipetteDevice.getRecordingChambers():
            if well.containsPoint(next_job.position[:2]):
                job = job_queue.queued_jobs.pop(next_idx)
                job.set_protocol(job_queue.protocol)
                job.assign_pipette(patch_pipette)
                return job


def request_job_fair_using_recording_chambers(job_queue, patch_pipette):
    with job_queue.lock:
        if not job_queue.enabled:
            return None

        if len(job_queue.queued_jobs) == 0:
            return None

        positions = np.array([job.position[:2] for job in job_queue.queued_jobs])

        wells = patch_pipette.pipetteDevice.getRecordingChambers()
        for well in wells:
            available = [well.containsPoint(pos) for pos in positions]
            if any(available):
                job_index = np.argwhere(available)[0, 0]
                job = job_queue.queued_jobs.pop(job_index)
                job.set_protocol(job_queue.protocol)
                job.assign_pipette(patch_pipette)
                return job

        return None


def request_job_fair_geometric(job_queue, patch_pipette):
    # The following code is useful for single-chamber rigs. TODO figure out how to integrate this.
    boundaries = job_queue.module.boundaries_by_pipette[patch_pipette.pipetteDevice]
    lower = np.arctan2(*boundaries[0][::-1])
    upper = np.arctan2(*boundaries[1][::-1])

    positions = np.array([job.position[:2] for job in job_queue.queued_jobs])
    # TODO the center might only need to account for currently active or queued jobs
    all_positions = np.array([job.position[:2] for job in job_queue.all_jobs])
    center = np.mean(all_positions, axis=0)

    diff = positions - center
    angles = np.arctan2(diff[:, 1], diff[:, 0])
    if lower > upper:
        slice_mask = (angles > upper) & (angles < lower)
    elif lower == upper:
        # This implies we have only one pipette
        slice_mask = np.ones(positions.shape[0]).astype(bool)
    else:
        slice_mask = (angles < upper) & (angles > lower)
    dist = (diff ** 2).sum(axis=1) ** 0.5
    dist[~slice_mask] = np.inf
    # TODO the selection of job must account for safe distances between pipette tips
    closest = int(np.argmin(dist))  # closest to the center
    if dist[closest] == np.inf:
        return None
