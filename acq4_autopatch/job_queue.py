import numpy as np
from acq4.util.Mutex import Mutex


def _polar2z(r, theta):
    return r * np.exp(1j * theta)


def _z2polar(z):
    return (np.abs(z), np.angle(z))


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
        self.center = module.plate_center()
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
            lower = _z2polar(boundaries[0])
            upper = _z2polar(boundaries[1])
            # TODO consider the degenerate case: only one pipette
            # TODO consider the semi-degenerate case: only two pipettes
            # TODO the center of the jobs maybe needs to account for all currenttly active jobs

            # # current pipette position
            # pos = np.array(patch_pipette.pipetteDevice.globalPosition())
            #
            # # all job positions
            # positions = np.array([job.position for job in self.queued_jobs])
            #
            # # which quadrant does this pipette belong in?
            # pip_quad = np.array(self.pipettes[patch_pipette.name()]).astype(bool)
            #
            # # mask cells that are not in the same quadrant
            # quad_center = np.array(self.center[:2])
            # cell_quads = positions[:, :2] > quad_center
            # quad_mask = (cell_quads == pip_quad[None, :]).all(axis=1)

            positions = np.array([job.position for job in self.queued_jobs])
            center = np.mean(positions, axis=0)

            # find closest cell to this pipette, excluding other slices
            diff = positions - np.array(center).reshape(1, 3)
            dist = (diff ** 2).sum(axis=1) ** 0.5
            # dist[~quad_mask] = np.inf
            closest = np.argmin(dist)
            if dist[closest] == np.inf:
                return None

            job = self.queued_jobs.pop(closest)
            job.set_protocol(self.protocol)
            job.assign_pipette(patch_pipette)
            return job
