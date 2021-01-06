import numpy as np
from acq4.util.Mutex import Mutex


class JobQueue(object):
    """Stores a list of jobs and assigns them by request.

    Pipettes are selected for each job based on the quadrant that the target appears in.
    """

    def __init__(self, patch_device_names, module):
        self.pipettes = patch_device_names
        self.module = module
        self.protocol = None
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

    def request_job(self, patch_pipette):
        # Simple implementation: return the job nearest to the current pipette position.
        # Only jobs in the same quadrant as the pipette are considered.

        with self.lock:
            if not self.enabled:
                return None

            if len(self.queued_jobs) == 0:
                return None

            boundaries = self.module.boundaries_by_pipette[patch_pipette.pipetteDevice]
            lower = np.arctan2(*boundaries[0][::-1])
            upper = np.arctan2(*boundaries[1][::-1])

            # TODO the center of the jobs maybe needs to account for all currently active jobs
            # TODO the selection of job must account for safe distances between pipette tips

            positions = np.array([job.position[:2] for job in self.queued_jobs])
            all_positions = np.array([job.position[:2] for job in self.all_jobs])
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
            closest = int(np.argmin(dist))  # closest to the center
            if dist[closest] == np.inf:
                return None

            job = self.queued_jobs.pop(closest)
            job.set_protocol(self.protocol)
            job.assign_pipette(patch_pipette)
            return job
