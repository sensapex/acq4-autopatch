# ACQ4-Autopatch
Automated cell patching extension for ACQ4

# Installation

TODO how are we distributing this?

Install the package into your environment with e.g.

```
conda develop acq4_autopatch
```

Customize the following and add it to the `modules:` section of your ACQ4 `default.cfg` file:

```yaml
    Autopatch:
        module: 'acq4_autopatch.module.AutopatchModule'
        config:
            imagingDevice: 'Camera'
            patchDevices:
                PatchPipette1: (0, 0)  # bottom-left quad
                PatchPipette2: (50*mm, 0)  # bottom-right quad
                PatchPipette3: (0, 50*mm)  # top-left quad
                PatchPipette4: (50*mm, 50*mm)  # top-right quad
            plateCenter: (0, 0, 0)
            wellPositions: [(0, 0), (50*mm, 0), (0, 50*mm), (50*mm, 50*mm)]
            safeMove: True
            patchStates:
                cell detect:
                    maxAdvanceDistancePastTarget: 1*um
                seal:
                    autoSealTimeout: 60
                    pressureMode: 'auto'
                cell attached:
                    autoBreakInDelay: 5.0
                clean:
                    approachHeight: 3*mm
                    cleanSequence: [(-35e3, 1.0), (65e3, 1.5)] * 5
                    rinseSequence: [(-35e3, 3.0), (65e3, 15.0)]
```

# Usage

TODO create and then link to video explanation.

Briefly:
1. Make sure you have an active Storage directory in the DataManager module.
1. Open the Camera module.
   1. The first time through, use this to move each pipette into its home, clean and rinse positions.
   1. In the main ACQ4 Manager window, save the home on each Manipulator.
   1. In the main ACQ4 Manager window, save the clean and rinse on each PatchPipette.
   1. Do any other calibration necessary.
1. For each pipette, open a separate TaskRunner module.
   1. Enable the Clamp associated with this pipette.
   1. Configure the tasks to be performed after a cell is patched.
1. Open the MultiPatch module. This is useful for monitoring.
1. Open the Autopatch module.
   1. Press "Add Points" and add one in the Camera for every cell you'd like to patch. Repeat for each well.
   1. Pick your acquisition protocol.
   1. Press "Start"
1. Monitor status in the "Pipettes" pane or in the MultiPatch window.
1. Read through results or look at errors in the "Results" pane.

# Licensing

All software copyright (c) 2019-2020 Sensapex. All rights reserved. It is offered under multiple different
licenses, depending on your needs:

 * A commercial license is appropriate for development of proprietary/commercial software where you do not want
   to share any source code with third parties or otherwise cannot comply with the terms of the GNU LGPL
   version 3. To purchase a commercial license, contact office@sensapex.com
 * Licensed under the GNU Lesser General Public License (LGPL) version 3 is appropriate for the development of
   open-source applications, provided you can comply with the terms and conditions of the GNU LGPL version 3 (or
   GNU GPL version 3). See [LGPL-3](LGPL-3) for details.