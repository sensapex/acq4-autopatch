import numpy as np
from acq4.util.Mutex import Mutex


class JobQueue(object):
    """Stores a list of jobs and assigns them by request.

    Pipettes are selected for each job based on the quadrant that the target appears in.
    """

    def __init__(self, pipettes, module):
        self.pipettes = pipettes  # {pipette_name: quadrant}
        self.module = module
        self.protocol = None
        self.all_jobs = []
        self.queued_jobs = []
        self.center = module.plateCenter()
        self.enabled = False
        self.positions = np.empty((0, 3))
        self.lock = Mutex(recursive=True)

    def setProtocol(self, prot):
        self.protocol = prot
        self.setJobs(self.all_jobs)

    def setEnabled(self, en):
        """If enabled, then requestJob() will attempt to return the next available job.
        If disabled, then requestJob() will return None.
        """
        self.enabled = en

    def setJobs(self, jobs):
        with self.lock:
            # queue up all jobs that have not run this protocol yet
            self.all_jobs = jobs
            self.queued_jobs = [j for j in jobs if self.protocol.name not in j.assigned_protocols]

    def requestJob(self, pipette):
        # Simple implementation: return the job nearest to the current pipette position.
        # Only jobs in the same quadrant as the pipette are considered.

        with self.lock:
            if not self.enabled:
                return None

            if len(self.queued_jobs) == 0:
                return None

            # current pipette position
            pos = np.array(pipette.pipetteDevice.globalPosition())

            # all job positions
            positions = np.array([job.position for job in self.queued_jobs])

            # which quadrant does this pipette belong in?
            pip_quad = np.array(self.pipettes[pipette.name()]).astype(bool)

            # mask cells that are not in the same quadrant
            quad_center = np.array(self.center[:2])
            cell_quads = positions[:, :2] > quad_center
            quad_mask = (cell_quads == pip_quad[None, :]).all(axis=1)

            # find closest cell to this pipette, excluding other quads
            diff = positions - np.array(pos).reshape(1, 3)
            dist = (diff ** 2).sum(axis=1) ** 0.5
            dist[~quad_mask] = np.inf
            closest = np.argmin(dist)
            if dist[closest] == np.inf:
                return None

            job = self.queued_jobs.pop(closest)
            job.setProtocol(self.protocol)
            job.assignPipette(pipette)
            return job
