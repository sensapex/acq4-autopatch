import numpy as np
from acq4.devices.Sensapex import Sensapex


class AutopatchCustomStage(Sensapex):
    """Implement extra motion planning to protect objective.
    """

    def _move(self, abs, rel, speed, linear, protected=True):
        if not protected:
            return Sensapex._move(self, abs, rel, speed, linear)

        wells = np.array(self.config["wellPositions"]) * 1e9
        radius = self.config["wellRadius"] * 1e9
        wellZ = self.config["wellMaxZ"] * 1e9
        safeZ = self.config["safeMaxZ"] * 1e9

        pos1 = np.array(self.getPosition())
        pos2 = np.array(self._toAbsolutePosition(abs, rel))

        # lateral distances from center of each well
        dist1 = ((wells - pos1[np.newaxis, :2]) ** 2).sum(axis=1) ** 0.5
        dist2 = ((wells - pos2[np.newaxis, :2]) ** 2).sum(axis=1) ** 0.5

        # closest well
        well1 = np.argmin(dist1)
        well2 = np.argmin(dist2)

        # are we starting / ending in the same well?
        startInWell = np.any(dist1 < radius)
        endInWell = np.any(dist2 < radius)
        changeWell = well1 != well2
        # print("startInWell: %s  endInWell: %s   changeWell: %s   wells: %s %s" % (startInWell, endInWell, changeWell, well1, well2))

        # don't move too high
        maxZ = wellZ if endInWell else safeZ
        pos2[2] = min(pos2[2], maxZ)

        if startInWell and endInWell and not changeWell:
            # no danger here, just move
            # print("   no well change; moving directly")
            return Sensapex._move(self, abs=pos2, rel=None, speed=speed, linear=linear)

        # decide on a safe path
        path = []
        # print("stage move path:")

        # First move down to safe Z if needed
        lastZ = pos1[2]
        if pos1[2] > safeZ:
            wp1 = pos1.copy()
            wp1[2] = min(safeZ, pos2[2])
            lastZ = wp1[2]
            path.append({"abs": wp1, "speed": "fast", "protected": False})
            # print("   - move focus down")

        # Next move just XY
        wp2 = pos2.copy()
        wp2[2] = lastZ
        path.append({"abs": wp2, "speed": speed, "protected": False})
        # print("   - move xy")

        # Finally correct Z if needed
        if wp2[2] != pos2[2]:
            path.append({"abs": pos2, "speed": "fast", "protected": False})
            # print("   - move focus up")

        return self.movePath(path)
