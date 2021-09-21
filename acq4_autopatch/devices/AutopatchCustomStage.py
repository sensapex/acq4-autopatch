import numpy as np
from acq4.devices.Sensapex import Sensapex


class AutopatchCustomStage(Sensapex):
    """Implement extra motion planning to prevent collisions.
    """

    def _move(self, abs, rel, speed, linear, protected=True):
        if not protected:
            return Sensapex._move(self, abs, rel, speed, linear)

        scale = self.scale[2]
        wells = np.array(self.config["wellPositions"]) / scale
        radius = self.config["wellRadius"] / scale
        max_z_in_well = self.config["insideWellMaxZ"] / scale
        max_z_out_of_well = self.config["outOfWellMaxZ"] / scale

        current_pos = np.array(self.getPosition())
        dest_pos = np.array(self._toAbsolutePosition(abs, rel))

        # lateral distances from center of each well
        current_dist_from_wells = ((wells - current_pos[np.newaxis, :2]) ** 2).sum(axis=1) ** 0.5
        dest_dist_from_wells = ((wells - dest_pos[np.newaxis, :2]) ** 2).sum(axis=1) ** 0.5

        current_closest_well = np.argmin(current_dist_from_wells)
        dest_closest_well = np.argmin(dest_dist_from_wells)

        # are we starting / ending in the same well?
        start_in_well = np.any(current_dist_from_wells < radius)
        end_in_well = np.any(dest_dist_from_wells < radius)
        change_well = current_closest_well != dest_closest_well

        # don't move too high
        max_z = max_z_in_well if end_in_well else max_z_out_of_well
        dest_pos[2] = min(dest_pos[2], max_z)

        if start_in_well and end_in_well and not change_well:
            # no danger here, just move
            return Sensapex._move(self, abs=dest_pos, rel=None, speed=speed, linear=linear)

        path = []

        # First move down to safe Z if needed
        last_z = current_pos[2]
        if current_pos[2] > max_z_out_of_well:
            wp1 = current_pos.copy()
            wp1[2] = min(max_z_out_of_well, dest_pos[2])
            last_z = wp1[2]
            path.append({"abs": wp1, "speed": "fast", "protected": False})

        # Next move just XY
        wp2 = dest_pos.copy()
        wp2[2] = last_z
        path.append({"abs": wp2, "speed": speed, "protected": False})

        # Finally correct Z if needed
        if wp2[2] != dest_pos[2]:
            path.append({"abs": dest_pos, "speed": "fast", "protected": False})

        return self.movePath(path)
