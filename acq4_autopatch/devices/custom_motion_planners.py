"""
ACQ4's built in pipette motion planning takes extra steps to avoid collisions with upright microscope objectives. 
On the inverted scope, we don't need to avoid the objective.
"""
from acq4.devices.Pipette import Pipette
from acq4.devices.Pipette.planners import PipetteMotionPlanner


class TargetMotionPlanner(PipetteMotionPlanner):
    """Move directly to target
    """

    def _move(self):
        pip = self.pip
        speed = self.speed
        target = pip.targetPosition()
        return pip._moveToGlobal(target, speed=speed)


Pipette.defaultMotionPlanners["target"] = TargetMotionPlanner


class ApproachMotionPlanner(PipetteMotionPlanner):
    """Move directly to approach position
    """

    def _move(self):
        pip = self.pip
        speed = self.speed
        target = pip.targetPosition()
        target[2] = self.pip.approachDepth()
        return pip._moveToGlobal(target, speed=speed)


Pipette.defaultMotionPlanners["approach"] = ApproachMotionPlanner
